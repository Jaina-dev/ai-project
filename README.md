# Placement Eligibility Checker

A console tool for a college placement cell. It reads job posts, uses an LLM to pull out each post's eligibility criteria, checks those criteria against the post, and matches them against the student list. It produces a **draft** list of eligible students per job. The placement officer checks every list before it is shared.

CIT AI-Native Engineering Programme · Semester 1 · Assessment 5

## How it works

1. `jobs.csv` and `students.csv` are loaded.
2. For each post, **only the post text** and `system_prompt.txt` are sent to the LLM (Groq `openai/gpt-oss-120b`, or OpenRouter `google/gemma-4-31b-it:free` if only that key is set). Student data never leaves the computer.
3. The reply is checked by `is_valid()`. An invalid reply is retried once, then the post goes to review.
4. Only the five expected fields are copied from the reply.
5. `check_facts()` removes anything the post does not say: a branch it never names, a made-up "ALL", a CGPA that is really a percentage, a batch year or backlog rule that is not written.
6. `job_status()` marks the post `matched`, or `needs_review` if it has no branches or no CGPA.
7. `is_eligible()` compares each student with the criteria using plain Python.
8. Four report files are written.

## Setup

1. Install Python 3.9 or newer. No extra packages are needed.
2. Get a free key from [console.groq.com](https://console.groq.com/keys) or [openrouter.ai](https://openrouter.ai/keys).
3. Create a file named `.env` in this folder with one line (no spaces around `=`):

   ```
   GROQ_API_KEY=your-key-here
   ```

   For OpenRouter use `OPENROUTER_API_KEY=your-key-here`. If both are set, Groq is used.

4. `.env` is listed in `.gitignore`, so it is never committed. Run `git status` before your first commit and check that `.env` is not listed.

## Run

```
python main.py                  # process all posts and write the four output files
python test_checker.py          # run the offline tests (no key needed)
python test_checker.py live     # the tests, plus one real post sent to the LLM
```

## Files

| File | What it is |
|---|---|
| `main.py` | The program |
| `system_prompt.txt` | The LLM prompt (Authority, Exemplar, Constraint, Rubric, Metadata) |
| `jobs.csv` | 10 job posts |
| `students.csv` | 24 made-up students |
| `test_checker.py` | Eval harness (5 posts), red-team tests and unit tests |
| `eval_results.txt` | Results of the test run, including one live call |
| `job_summary.csv` | Each post's criteria, status and eligible count |
| `eligible.csv` | One row per eligible student per job |
| `review.csv` | Posts the placement officer must read, with the reason |
| `summary.txt` | Eligible count per job, and students eligible for no job yet |
| `spec.md` | The specification |
| `judgement_framework.md` | Who does each step, the cost of errors, and the human checkpoint |
| `cost_latency_note.md` | API calls, time and cost per day |
| `ai_decision_journal.md` | Main decisions and how each was checked |
| `reflection.md` | 400-word reflection |

## Safety design

- **LLM reads, Python decides.** Eligibility is plain comparison on floats and integers.
- **Private data stays local.** The request body holds only the system prompt and the post. A test checks this.
- **Never trust a reply.** Every reply is validated and fact-checked against the post.
- **Fail toward a human.** A percentage cut-off, a vague cut-off, an "except" clause, a bad reply, no key or no network all send the post to `review.csv` with a reason.
- **One bad post never stops the run.** Each file is also written separately, so a file open in Excel does not block the others.

## Known limitations

- The models are pinned in the `PROVIDERS` list in `main.py`. Free models change or retire, so if one stops working, change its `model` there. This already happened: Groq retired `llama-3.3-70b-versatile` on 16 Aug 2026 (every call returned HTTP 404), so the project now uses `openai/gpt-oss-120b`. `qwen/qwen3.6-27b` is Groq's other suggested replacement.
- `gpt-oss-120b` is a reasoning model, so `max_tokens` is set to 2000 to leave room for its thinking and the JSON reply.
- OpenRouter free models allow about 20 requests a minute and 50 a day (1,000 a day after $10 of credits), shared by all free models on the account. That is why Groq is the first choice. A full run uses 10 to 20 requests, so avoid many repeat runs in one day. The program pauses between posts, waits after a per-minute 429, and stops calling the LLM if the daily limit is reached.
- The fact check needs the word "gpa" in the post, so "grade point average" goes to review.
- The fact check only removes values. It does not add a branch or backlog rule that the LLM left out.
- The tests use a fake LLM. They prove the checks, not how accurate a real model is.
- `summary.txt` lists students eligible for no job using matched posts only. It names the posts still in review.

## Human checkpoint

Every output is a draft. The placement officer reads `review.csv` and checks each list before anything goes to a company or to students.
