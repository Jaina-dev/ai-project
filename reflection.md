# Reflection: Placement Eligibility Checker

When I started, I thought the hard part would be getting the LLM to read job posts. The hard part was deciding how much to trust what the LLM said.

The most important decision was the split of jobs: the LLM reads, and Python decides. An LLM understands posts written in many styles, but it can also invent a value that sounds right. It might turn "70 percent" into a CGPA of 7.0. If that went straight into the eligible list, a wrong list could reach a company. So every reply passes through `is_valid()` and `check_facts()`, and a value stays only if the post says it. An empty value is better than a wrong one.

I also learned to design for failure. The tool must not crash when there is no API key, no internet or a bad reply. Each of these ends in `needs_review` with a reason. This was tested for real: Groq retired my model, every call returned an error, and the tool still finished and sent every post to a person instead of crashing. Tests with a fake LLM made this practical, because I could simulate bad replies and a post that tries to add a student with the same result every run. My 45 tests pass, but they prove the checks work, not that a real model is always accurate.

The Judgment Framework changed how I thought about errors. A student wrongly included is visible, because the officer can compare the name with the post. A student wrongly left out is invisible. That is why unclear posts go to review instead of getting the most likely answer.

Three things I would do differently:

1. Write the spec first and test the prompt with real posts earlier. I found limits late, such as the fact check needing the word "gpa".
2. Pin one model from the start and check it is still available. Free models change, retire and have rate limits.
3. Keep test data and documents in step so the numbers match.

Three learnings I will keep:

1. Never use an LLM reply without checking it.
2. Keep private data away from the model and use plain code for exact decisions.
3. When unsure, hand the decision to a human and say why.

The placement officer stays responsible for every list. My tool saves their time but does not replace their judgment.
