# Cost and Latency Note

Token and cost figures are **estimates**. The run details below were measured on 22 Nov 2026 with Groq `openai/gpt-oss-120b`.

**Measured run:** 10 posts, 11 API calls (J03 needed one retry after "Remote end closed connection"), and all 10 posts came back valid. Total run time: about 48 seconds.

## How many API calls does one day need?

The program makes **one call per job post**. It sends only the post and the system prompt, and there is one extra call per post when a reply is invalid or a call fails (the single retry).

| Day | Posts | Calls (no retries) | Calls (every post retried) |
|---|---|---|---|
| Normal day (a few posts a week, so 0–3 a day) | 2 | 2 | 4 |
| Busy day (the size of `jobs.csv`) | 10 | 10 | 20 |

The matching step is plain Python on 24 students. It makes **no API calls** and takes well under a second.

## Size of one call (rough)

| Part | Approx. tokens |
|---|---|
| System prompt (`system_prompt.txt`, 4 examples, about 2,400 characters) | ~600 |
| Job post (about 77 characters on average) | ~20 |
| LLM reply (one JSON object) | ~70, plus extra tokens if the model thinks first |
| **Per call** | **~620 in, ~70 out** |

(Estimated at roughly 4 characters per token.)

## Latency

- **Per call:** about 3–10 seconds for a typical hosted model. Free models can be slower because of queueing. The request timeout is 60 seconds.
- **Retry:** waits 2 seconds, then calls once more. After a per-minute rate limit (429) it waits 20 seconds. The program also pauses 4 seconds between posts, so 10 posts take at least 36 seconds of pauses.
- **A busy day (10 posts, one after another):** about 30–100 seconds in total.
- **Worst case (network down):** the LLM is skipped after 3 failed attempts in a row. Because a post's retry still runs, up to 4 timeouts happen, so a run can take about **4 minutes** before all remaining posts go straight to review.
- **Everything else** (loading CSVs, fact checks, matching, writing four files): under a second.

## Cost per day

**Current setup: Groq free tier with `openai/gpt-oss-120b` (OpenRouter `google/gemma-4-31b-it:free` as the other option), so $0.** Groq's free tier has its own per-minute and per-day limits, which are separate from OpenRouter's. Check them on console.groq.com before quoting numbers.

**OpenRouter free models:** OpenRouter free models allow about 20 requests a minute and 50 a day on an account with under $10 of lifetime credits (1,000 a day above that), shared by all free models. A busy day uses 10 to 20 requests, so only 2 to 5 full runs fit in a day. A limit sends the remaining posts to review.

**If a paid model were used** (assumed example price: $0.15 per million input tokens and $0.60 per million output tokens; check the real price on openrouter.ai before quoting it):

- One call ≈ (620 × $0.15 + 70 × $0.60) ÷ 1,000,000 ≈ **$0.00014**
- Normal day (2 posts): ≈ **$0.0003**
- Busy day (10 posts): ≈ **$0.0014**
- Worst case (20 calls): ≈ **$0.0027**

Even a busy day on a paid model costs well under one rupee, so cost is not the constraint. **Reliability and review time are.**

## What would change the numbers

- A longer system prompt costs more input tokens on every call. Adding examples improves accuracy but raises cost slightly.
- Sending several posts in one call would cut the number of calls, but one bad reply would then affect several posts. One post per call keeps failures separate.
- Pinning one `:free` model gives steadier speed and quality than the `openrouter/free` router, which can pick a different model each run. In my first real run the router gave empty replies on some posts.
- Models get retired. Groq shut down `llama-3.3-70b-versatile` on 16 Aug 2026, so every call returned HTTP 404 until I switched to `openai/gpt-oss-120b`. A reasoning model uses extra output tokens for thinking, so `max_tokens` is 2000.
