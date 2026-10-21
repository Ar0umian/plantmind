# Feedback notes (for the Nebius / NVIDIA / Tavily feedback section)

The feedback prize is judged on **completeness, actionability and potential impact**. Write only what you actually
observed. Fill the log while you work, then turn it into the submission text. Do not invent measurements:
paste numbers from `out/live_eval.md`.

## Log (add a line whenever something surprises you)
| Date | Tool | What happened | Impact | Suggestion |
|---|---|---|---|---|
|  | Token Factory |  |  |  |
|  | Nemotron |  |  |  |
|  | Tavily |  |  |  |

## What to observe (checklist)
Nebius Token Factory
- Time from account creation to the first successful call; any step that was unclear.
- Was `list_models` / the model catalog enough to find the right Nemotron IDs?
- OpenAI-compatibility: anything in the OpenAI SDK that did not behave as expected.
- Latency per tier (Nano vs Super vs Ultra) and tokens per incident (from `out/live_eval.md`).
- Rate limits, errors, retries; how credits and usage were visible.
- Cost per incident compared with always using the largest model (the tier-routing benefit).

NVIDIA Nemotron
- Did each tier return valid JSON on the first try? How often did the validator drop IDs or fall back?
- Visible reasoning text (`<think>` blocks): did they interfere with JSON? (the client strips them)
- Quality: did the top cause match the scenario? Where was it wrong or over-confident?
- Differences between Nano, Super and Ultra for the same alert.

Tavily
- Relevance of the returned advisories for each incident type; any query wording that worked much better.
- Credits used per report.

## Draft structure for the final text (edit with real findings)
1. **Context** - what we built and how each tool was used (3 sentences).
2. **What worked well** - 3 concrete points with numbers.
3. **Friction we hit** - each with what we did about it.
4. **Concrete suggestions** - 3 to 5 actionable items (docs, defaults, error messages, catalog metadata).
5. **Impact** - why the fixes would help other builders.
