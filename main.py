"""Placement Eligibility Checker.

The LLM reads each job post and returns its criteria as JSON.
Python checks that reply against the post, then decides who is eligible.
Student data never goes to the LLM.

Run:  python main.py
Needs jobs.csv, students.csv, system_prompt.txt and a .env file with GROQ_API_KEY or OPENROUTER_API_KEY.
"""
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request

# Two providers, both OpenAI-style. The first one whose key is in .env is used.
PROVIDERS = [
    {"name": "Groq", "key_name": "GROQ_API_KEY",
     "url": "https://api.groq.com/openai/v1/chat/completions", "model": "openai/gpt-oss-120b"},
    {"name": "OpenRouter", "key_name": "OPENROUTER_API_KEY",
     "url": "https://openrouter.ai/api/v1/chat/completions", "model": "google/gemma-4-31b-it:free"},
]
PROMPT_FILE = "system_prompt.txt"
BRANCHES = ["CSE", "IT", "AIDS", "ECE", "EEE", "MECH", "CIVIL"]
FIELDS = ["branches", "min_cgpa", "max_backlogs", "batch", "summary"]
RETRY_WAIT = 2                       # seconds to wait before the one retry
RATE_LIMIT_WAIT = 20                 # seconds to wait after a per-minute limit (HTTP 429)
PAUSE_BETWEEN_POSTS = 4              # seconds between posts: free models allow about 20 requests a minute
MAX_NETWORK_FAILURES = 3             # after this many in a row, stop calling the LLM
network_failures = 0                 # counts network errors in a row

ALIASES = {"CSE": "CSE", "CS": "CSE", "COMPUTER SCIENCE": "CSE",
           "IT": "IT", "INFORMATION TECHNOLOGY": "IT",
           "AIDS": "AIDS", "AI&DS": "AIDS", "AI & DS": "AIDS", "AI AND DS": "AIDS", "AI/DS": "AIDS",
           "ECE": "ECE", "EEE": "EEE",
           "MECH": "MECH", "MECHANICAL": "MECH", "CIVIL": "CIVIL"}

# How each branch can be written in a post. (?-i:...) means capitals only,
# so the ordinary word "it" is never read as the IT branch.
BRANCH_PATTERNS = {
    "CSE": re.compile(r"(?-i:\bCSE\b)|computer science", re.I),
    "IT": re.compile(r"(?-i:\bIT\b)(?!\s+(?:company|companies|firm|firms|sector|industry|services|roles?|jobs?)\b)"
                     r"|information technology", re.I),
    "AIDS": re.compile(r"(?-i:\bAIDS\b)|\bAI\s*(?:&|and|/)\s*DS\b|artificial intelligence (?:and|&) data science", re.I),
    "ECE": re.compile(r"(?-i:\bECE\b)|electronics", re.I),
    "EEE": re.compile(r"(?-i:\bEEE\b)|electrical", re.I),
    "MECH": re.compile(r"(?-i:\bMECH\b)|mechanical", re.I),
    "CIVIL": re.compile(r"\bcivil\b", re.I),
}
ALL_PHRASE = re.compile(r"\b(?:any|all|every)\s+(?:\w+\s+)?branch(?:es)?\b", re.I)
EXCLUDE_PHRASE = re.compile(r"\b(?:except|excluding|exclude|other than|apart from|barring|but not|not including)\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


# ---------- loading ----------

def load_env(path=".env"):
    """Read NAME=value lines from .env into the environment (quotes removed)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass                                   # no .env file: the key may be set another way


def normalize_branch(text):
    """' ai&ds ' -> 'AIDS'. Unknown names are returned in capitals."""
    key = " ".join(text.upper().split())
    return ALIASES.get(key, key)


def read_rows(path):
    """Read a CSV into a list of dicts with lower-case headers. Handles BOM and tabs."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            first_line = f.readline()
            f.seek(0)
            delimiter = "\t" if "\t" in first_line and "," not in first_line else ","
            rows = []
            for row in csv.DictReader(f, delimiter=delimiter):
                rows.append({k.strip().lower(): (v or "").strip()
                             for k, v in row.items() if k is not None})
            return rows
    except OSError as e:
        print("Cannot read", path, "-", e)
        return []


def load_jobs(path="jobs.csv"):
    jobs = []
    for number, row in enumerate(read_rows(path), start=2):
        if not row.get("id") or not row.get("post"):
            print("  Skipping job row", number, "- missing id or post")
            continue
        jobs.append({"id": row["id"], "company": row.get("company", ""), "post": row["post"]})
    if not jobs:
        print("No job posts found in", path)
    return jobs


def load_students(path="students.csv"):
    students = []
    for number, row in enumerate(read_rows(path), start=2):
        try:
            if not row["roll"]:
                raise ValueError("empty roll")
            students.append({"roll": row["roll"], "name": row["name"],
                             "branch": normalize_branch(row["branch"]),
                             "cgpa": float(row["cgpa"]),        # a number, not text
                             "backlogs": int(row["backlogs"]),
                             "batch": int(row["batch"])})
        except (KeyError, ValueError) as e:
            print("  Skipping student row", number, "-", e)
    if not students:
        print("No students found in", path)
    return students


# ---------- the LLM ----------

def pick_provider():
    """The first provider whose API key is set, or None."""
    for provider in PROVIDERS:
        if os.environ.get(provider["key_name"]):
            return provider
    return None


def call_llm(system_prompt, post):
    """Send ONLY the system prompt and the post. Returns the reply text."""
    provider = pick_provider()
    if provider is None:
        raise RuntimeError("No API key found: set GROQ_API_KEY or OPENROUTER_API_KEY in .env")
    body = json.dumps({"model": provider["model"], "temperature": 0, "max_tokens": 2000,
                       "messages": [{"role": "system", "content": system_prompt},
                                    {"role": "user", "content": post}]}).encode("utf-8")
    request = urllib.request.Request(provider["url"], data=body,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "placement-checker/1.0",
                                              "Authorization": "Bearer " + os.environ[provider["key_name"]]})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read())
    if "error" in data:                                      # some providers answer 200 with an error
        raise RuntimeError("API error: " + str(data["error"])[:200])
    choice = data["choices"][0]
    text = choice["message"].get("content")
    if not text:                                             # some models return an empty reply
        raise RuntimeError("the model returned an empty reply (finish_reason: %s)" % choice.get("finish_reason"))
    return text


def is_valid(d):
    """True only if the reply has the right keys, types and ranges."""
    if not isinstance(d, dict) or any(k not in d for k in FIELDS):
        return False
    b = d["branches"]
    if not isinstance(b, list) or not all(x in BRANCHES + ["ALL"] for x in b):
        return False
    if "ALL" in b and b != ["ALL"]:
        return False
    c = d["min_cgpa"]
    if c is not None and not (isinstance(c, (int, float)) and not isinstance(c, bool) and 0 <= c <= 10):
        return False
    m = d["max_backlogs"]
    if m is not None and not (isinstance(m, int) and not isinstance(m, bool) and m >= 0):
        return False
    y = d["batch"]
    if y is not None and not (isinstance(y, int) and not isinstance(y, bool) and 2000 <= y <= 2100):
        return False
    return isinstance(d["summary"], str) and len(d["summary"].split()) <= 12


def error_text(e):
    """The short message OpenRouter sends with an HTTP error (empty if there is none)."""
    try:
        return e.read().decode("utf-8", "replace")[:200]
    except Exception:
        return ""


def read_criteria(post):
    """Ask the LLM, validate the reply, retry once. Returns the five fields, or None."""
    global network_failures
    if network_failures >= MAX_NETWORK_FAILURES:
        print("  Network failed", MAX_NETWORK_FAILURES, "times in a row - skipping the LLM")
        return None
    try:
        with open(PROMPT_FILE, encoding="utf-8") as f:
            system_prompt = f.read()
    except OSError as e:
        print("  Cannot read the system prompt:", e)
        return None

    for attempt in (1, 2):
        wait = RETRY_WAIT
        try:
            text = call_llm(system_prompt, post)
            data = json.loads(text[text.find("{"): text.rfind("}") + 1])
            if is_valid(data):
                network_failures = 0
                return {k: data[k] for k in FIELDS}         # copy only the five fields
            print("  LLM attempt", attempt, "failed: reply was not valid")
        except urllib.error.HTTPError as e:
            detail = error_text(e)
            if e.code == 429 and ("per-day" in detail.lower() or "per day" in detail.lower()):
                network_failures = MAX_NETWORK_FAILURES     # daily limit used up: stop calling the LLM
                print("  Daily limit reached - skipping the LLM.", detail)
                return None
            if e.code == 429:                               # too many requests this minute: wait longer
                wait = RATE_LIMIT_WAIT
                print("  LLM attempt", attempt, "rate limited (429), waiting", wait, "seconds", detail)
            else:
                network_failures += 1
                print("  LLM attempt", attempt, "failed (HTTP", e.code, "):", detail)
        except OSError as e:                                # network problems (URLError is an OSError)
            network_failures += 1
            print("  LLM attempt", attempt, "failed (network):", e)
        except Exception as e:                              # no key, bad JSON, odd reply
            print("  LLM attempt", attempt, "failed:", e)
        if attempt == 1:
            time.sleep(wait)
    return None


# ---------- fact check ----------

def number_in_post(post, value):
    """True if the number is written in the post and is not a percentage."""
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(%|percentage|percent|per cent)?", post, re.I):
        if float(m.group(1)) == float(value) and not m.group(2):
            return True
    return False


def has_exclusion(post):
    """True if a branch is named after except / excluding / other than ... in the same sentence."""
    for m in EXCLUDE_PHRASE.finditer(post):
        rest = post[m.end():].split(".")[0]
        if any(p.search(rest) for p in BRANCH_PATTERNS.values()):
            return True
    return False


def backlog_supported(post, value):
    """True if the post's own words support this backlog limit."""
    low = post.lower()
    if not re.search(r"backlog|arrear", low):
        return False
    if value == 0:
        return bool(re.search(r"\b(?:no|zero|nil|none|without)\b|not allowed|not permitted|not eligible", low))
    if any(int(n) == value for n in re.findall(r"\d+", low)):
        return True
    return any(re.search(r"\b" + word + r"\b", low) for word, n in NUMBER_WORDS.items() if n == value)


def check_facts(criteria, post):
    """Keep only what the post really says. Works on a copy."""
    c = dict(criteria)
    low = post.lower()

    if has_exclusion(post):
        c["branches"] = []                                  # unclear: a person reads it
    elif c["branches"] == ["ALL"]:
        if not ALL_PHRASE.search(post):
            c["branches"] = []
    else:
        c["branches"] = [b for b in c["branches"] if BRANCH_PATTERNS[b].search(post)]

    if c["min_cgpa"] is not None and ("gpa" not in low or not number_in_post(post, c["min_cgpa"])):
        c["min_cgpa"] = None
    if c["batch"] is not None and not re.search(r"\b" + str(c["batch"]) + r"\b", post):
        c["batch"] = None
    if c["max_backlogs"] is not None and not backlog_supported(post, c["max_backlogs"]):
        c["max_backlogs"] = None
    return c


# ---------- status and matching ----------

def job_status(c):
    if not c["branches"] or c["min_cgpa"] is None:
        return "needs_review"
    return "matched"


def is_eligible(s, c):
    """Plain comparisons only. Student data never leaves this computer."""
    if c["min_cgpa"] is None:
        return False
    if "ALL" not in c["branches"] and s["branch"] not in c["branches"]:
        return False
    if s["cgpa"] < c["min_cgpa"]:
        return False
    if c["max_backlogs"] is not None and s["backlogs"] > c["max_backlogs"]:
        return False
    if c["batch"] is not None and s["batch"] != c["batch"]:
        return False
    return True


def review_reason(post, c):
    """Why a post needs the placement officer."""
    if c is None:
        return "LLM gave no usable reply (key, network or bad JSON)"
    reasons = []
    if not c["branches"]:
        if has_exclusion(post):
            reasons.append("branch exclusion (except/excluding), read the post")
        else:
            reasons.append("no branch named in the post")
    if c["min_cgpa"] is None:
        if re.search(r"%|percent", post, re.I):
            reasons.append("cut-off is a percentage or vague, not a CGPA")
        elif "gpa" not in post.lower():
            reasons.append("no CGPA written in the post")
        else:
            reasons.append("CGPA could not be confirmed in the post")
    return "; ".join(reasons)


# ---------- reports ----------

def safe_write(filename, write_fn):
    """Write one file. If it fails (for example it is open in Excel) the others still get written."""
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            write_fn(f)
        print("  wrote", filename)
    except OSError as e:
        print("  COULD NOT WRITE", filename, "-", e, "(is it open in Excel?)")


def write_reports(results, students):
    def job_summary(f):
        w = csv.writer(f)
        w.writerow(["id", "company", "branches", "min_cgpa", "max_backlogs", "batch",
                    "summary", "status", "eligible_count"])
        for r in results:
            c = r["criteria"]
            w.writerow([r["id"], r["company"], "|".join(c["branches"]), c["min_cgpa"],
                        c["max_backlogs"], c["batch"], c["summary"], r["status"], len(r["eligible"])])

    def eligible(f):
        w = csv.writer(f)
        w.writerow(["job_id", "roll", "name", "branch", "cgpa"])
        for r in results:
            for s in r["eligible"]:
                w.writerow([r["id"], s["roll"], s["name"], s["branch"], s["cgpa"]])

    def review(f):
        w = csv.writer(f)
        w.writerow(["job_id", "company", "reason", "post"])
        for r in results:
            if r["status"] == "needs_review":
                w.writerow([r["id"], r["company"], r["reason"], r["post"]])

    def summary(f):
        f.write("DRAFT - placement officer must check before sharing\n\n")
        for r in results:
            f.write("%s %s: %s, %d eligible\n" % (r["id"], r["company"], r["status"], len(r["eligible"])))
        in_review = [r["id"] for r in results if r["status"] == "needs_review"]
        got_job = {s["roll"] for r in results for s in r["eligible"]}
        f.write("\nEligible for no job yet:\n")
        if in_review:
            f.write("(Posts still in review: %s. Some of these students may fit those posts.)\n"
                    % ", ".join(in_review))
        for s in students:
            if s["roll"] not in got_job:
                f.write("%s %s\n" % (s["roll"], s["name"]))

    safe_write("job_summary.csv", job_summary)
    safe_write("eligible.csv", eligible)
    safe_write("review.csv", review)
    safe_write("summary.txt", summary)


# ---------- main ----------

def process_job(job, students):
    """One post: LLM -> validate -> fact check -> status -> match."""
    criteria = read_criteria(job["post"])
    if criteria is None:
        empty = {"branches": [], "min_cgpa": None, "max_backlogs": None, "batch": None,
                 "summary": "LLM failed"}
        return {"id": job["id"], "company": job["company"], "post": job["post"], "criteria": empty,
                "status": "needs_review", "reason": review_reason(job["post"], None), "eligible": []}
    criteria = check_facts(criteria, job["post"])
    status = job_status(criteria)
    eligible = [s for s in students if is_eligible(s, criteria)] if status == "matched" else []
    reason = review_reason(job["post"], criteria) if status == "needs_review" else ""
    return {"id": job["id"], "company": job["company"], "post": job["post"], "criteria": criteria,
            "status": status, "reason": reason, "eligible": eligible}


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))     # find the files next to this program
    load_env()
    provider = pick_provider()
    if provider:
        print("Using", provider["name"], "-", provider["model"])
    jobs = load_jobs("jobs.csv")
    students = load_students("students.csv")
    if not jobs or not students:
        print("Nothing to do: need at least one job post and one student.")
        return
    results = []
    for number, job in enumerate(jobs):
        if number > 0:
            time.sleep(PAUSE_BETWEEN_POSTS)                   # stay under the free per-minute limit
        print("Processing", job["id"], job["company"])
        try:
            results.append(process_job(job, students))
        except Exception as e:                                # one bad post never stops the others
            print("  Unexpected problem:", e)
            empty = {"branches": [], "min_cgpa": None, "max_backlogs": None, "batch": None,
                     "summary": "error"}
            results.append({"id": job["id"], "company": job["company"], "post": job["post"],
                            "criteria": empty, "status": "needs_review",
                            "reason": "unexpected error: " + str(e), "eligible": []})
    write_reports(results, students)
    print("Done. Check job_summary.csv, eligible.csv, review.csv and summary.txt")


if __name__ == "__main__":
    main()
    