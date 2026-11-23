# Specification: Placement Eligibility Checker

CIT AI-Native Engineering Programme · Semester 1 · Assessment 5

## 1. What the tool does

The placement cell receives job posts written in many different ways. This console tool reads each post and uses an LLM to extract its eligibility criteria (branches, CGPA, backlogs, batch). Python then checks those criteria against the post and matches them against the student list. It produces a **draft** list of eligible students per job. The placement officer checks every list before it is shared.

**Inputs:** `jobs.csv` (id, company, post; 10 posts) and `students.csv` (roll, name, branch, cgpa, backlogs, batch; 24 made-up students).
**Outputs:** `job_summary.csv`, `eligible.csv`, `review.csv`, `summary.txt`.

## 2. Why student data stays in Python

- Only the text of one job post is sent to the LLM (with `system_prompt.txt`). Student names, rolls, CGPAs and backlogs never leave the computer.
- The LLM only reads. It never decides who is eligible. Python does that with plain comparisons, so the result is exact, repeatable and explainable.
- The API key is read from `.env` and is never written in the code or committed to Git.

## 3. What the LLM must return (JSON rules)

| Field | Allowed values | Rule |
|---|---|---|
| `branches` | list of CSE, IT, AIDS, ECE, EEE, MECH, CIVIL, or `["ALL"]` | Only branches the post names. Never guessed from the job role |
| `min_cgpa` | number 0–10, or null | Only a CGPA written in the post. A percentage is never converted |
| `max_backlogs` | whole number, or null | "No backlogs" means 0. Null if not mentioned |
| `batch` | year, or null | Only if written |
| `summary` | text, 12 words or fewer | Short description of the criteria |

Example: `{"branches": ["CSE","IT","AIDS"], "min_cgpa": 7.5, "max_backlogs": 0, "batch": 2027, "summary": "CSE, IT, AI&DS 2027, CGPA 7.5+, no backlogs"}`

## 4. Checks on every LLM reply

1. **Validate (`is_valid`)**: the reply must be a JSON object with correct types and ranges (known branches, CGPA 0–10, backlogs a whole number ≥ 0, batch 2000–2100, summary ≤ 12 words).
2. **Retry once** if the reply is invalid or the call fails. After that the post goes to `needs_review`.
3. **Copy only the five fields.** Any extra field (for example a "students" list) is dropped.
4. **Fact-check (`check_facts`)** against the post text. Anything the post does not support becomes empty or null:
   - A branch must be named in the post (for example "Mechanical" for MECH, "AI&DS" for AIDS).
   - `ALL` needs "any branch", "all branches" or similar wording.
   - If a branch appears inside an "except / excluding / other than" clause, the post is unclear and a human reads it.
   - The CGPA must be written as a number that is not a percentage, and the post must contain "gpa".
   - The batch year must be written in the post.
   - A backlog limit must match the post's words ("no", "zero", a number, or a number word).

## 5. Job status

After the fact check: if there are **no branches or no CGPA**, the job is `needs_review` (with the reason). Otherwise it is `matched`.

## 6. Eligibility (Python only)

A student is eligible for a matched job if all of these hold:

- their branch is in the list (or the list is `["ALL"]`)
- `cgpa >= min_cgpa` (compared as numbers, not text)
- `backlogs <= max_backlogs` (only if stated)
- `batch` equals the post's batch (only if stated)

A `needs_review` job never produces an eligible list.

## 7. Edge cases

| Case | What happens |
|---|---|
| Percentage cut-off ("70 percent", J04) | CGPA stays null, so the post goes to review |
| Vague cut-off ("top 10 percent", J06) | Review. "10" is not read as CGPA 10 |
| Post tells the LLM to add a student or change rules | Ignored. Only five fields are copied, and the prompt treats the post as data |
| LLM invents a branch, CGPA, backlog rule, batch or "ALL" | Dropped by the fact check |
| "Any branch except Civil" | Review |
| Bad JSON, API error, empty reply | One retry, then review with a reason |
| No API key | Run finishes, every post goes to review |
| Network fails 3 times in a row | LLM is skipped for the rest of the run |
| CGPA exactly equal to the cut-off | Eligible |
| CGPA "10.0" vs "7.5" | Compared as floats, so 10.0 is higher |
| CSV has a BOM, tabs, capital headers or bad rows | Handled. Bad rows are skipped with a message |
| Missing or empty input file | Clear message, no crash |
| Output file open in Excel | Reported. The other files are still written |
| A post that says "IT company" | "IT" is not read as a branch (capitals only, and not before words like "company") |

## 8. Human checkpoint

`summary.txt` starts with "DRAFT - placement officer must check before sharing". The officer reads `review.csv` and checks each list before anything goes to a company or to students.
