# PlantMind - Demo video script (target 2:45, hard limit 3:00)

Rules from the hackathon: under 3 minutes, public on YouTube, shows the project running, English (or English
subtitles), **no copyrighted music and no third-party branding**. Record in LIVE mode (`MOCK_LLM=0`, `MOCK_TAVILY=0`)
so the badge reads "AI: Nemotron live".

## Before recording
- `python scripts/live_eval.py` passes (all `yes`), `python scripts/verify_all.py` passes.
- Browser window 1440x900, zoom 100%, only the dashboard tab open, notifications off.
- Start the server fresh (`scripts/run_dev.sh`), press **Reset detection**, scenario **normal**.
- Record the screen at 1080p (QuickTime: File > New Screen Recording) with your voice. The tamper scenario needs about one
  minute to reach the alert: record it once in full, then **speed up the waiting part 4x** in the editor (iMovie) and keep
  the real-time parts at normal speed.
- No music. If you use subtitles, write them from the narration below.

## Shot list and narration

| Time | On screen | Narration (read this) |
|---|---|---|
| 0:00-0:15 | Dashboard, normal state, green Change Guard bar | "Small water utilities run critical plants with a few people. Knowledge sits in a few heads, and tampered protective logic looks perfectly normal." |
| 0:15-0:30 | Point at the four panels | "PlantMind reads the approved PLC program and turns it into knowledge: it documents the plant, guards the logic, tells faults from attacks, and explains every alert. It is advisory only." |
| 0:30-1:00 | Click **logic tamper**. Change Guard turns red; show the two findings, ATT&CK chips and the diff | "Someone loads a modified program. Change Guard sees it at once: interlock IL-04, the chlorine overdose trip, is still computed but no longer wired to the pump. Rules set the severity: critical. Nemotron then explains the hazard, and findings map to MITRE ATT&CK for ICS." |
| 1:00-1:35 | (sped up) chlorine chart passes 4.0 while P-201 keeps running; alert appears; show Model analysis | "A minute later the chlorine passes its limit and the pump does not trip. Nemotron Nano triages the alert, Nemotron Ultra ranks the causes: logic tampering first. Every claim cites an evidence ID produced by rule-based checks; anything else is discarded." |
| 1:35-1:55 | Open the incident report (new tab), scroll: causes, timeline, ATT&CK, references | "Each alert has an incident report: evidence, ranked causes, program integrity, timeline, decisions, ATT&CK mapping, and recent advisories found live with Tavily." |
| 1:55-2:15 | Click Approve; switch to **spoofed reading**; show flat level and collapsing flow | "A spoofed sensor is different. The PLC is fooled, so no interlock fires. Physics gives it away: the level stays flat while the pump runs and the flow collapses." |
| 2:15-2:35 | Assistant: "What does IL-04 do?" then type `stop P-201` | "Operators can ask questions grounded in the approved logic. And if someone asks it to act on equipment, it refuses: PlantMind never sends commands." |
| 2:35-2:45 | Plant documentation panel, then the README / GitHub page | "It also writes the operating document that lives in veterans' heads. Open source, MIT licensed. Nemotron runs on Nebius Token Factory. Link below." |

## Narration check
Read it aloud once with a timer: it should take about 2 minutes 20 seconds at a calm pace, leaving room for the demo pauses.
If you run long, cut the spoofed-reading part first, then the report scroll.
