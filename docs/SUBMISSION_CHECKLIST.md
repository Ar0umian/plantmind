# Submission checklist (Nebius x NVIDIA Global AI Hackathon)

Deadline: **Fri 30 Oct 2026, 10:00 AM Pacific = 8:00 PM Saudi time**. Target: submit by 29 Oct.

## Rules check (from the official rules)
- [ ] Runs on Nebius Token Factory with at least one NVIDIA open model (runtime call to the inference API) - live mode works.
- [ ] Track chosen: **Best Apps & Agents**.
- [ ] Project created during the submission period (26 Aug - 30 Oct 2026): git history shows it.
- [ ] Public GitHub repo with an open-source license visible at the top of the repo page (MIT).
- [ ] README with setup instructions and how Nemotron is used and where Token Factory helped.
- [ ] Demo video under 3 minutes, public on YouTube, no copyrighted music or third-party branding.
- [ ] Everything in English.
- [ ] Description text explaining features and functionality.
- [ ] Demo URL / hosted app / test build: the repository with the Quick Start (judges may judge from text, images and video alone).
- [ ] Feedback section completed (for the Most Valuable Feedback prize).
- [ ] Tavily: the solution makes a runtime call to the Tavily API (reports) - mention it in the text and the video.

## Before publishing the repository
- [ ] `python scripts/verify_all.py` shows no FAIL.
- [ ] `git ls-files | grep -E "(^|/)\.env$"` prints nothing (the key file is NOT tracked).
- [ ] No keys in the README, notes or screenshots.
- [ ] README: `TODO(live)` markers replaced with real measurements; screenshot and video link added.
- [ ] Repository is **public**, license shows as MIT, description and topics set.

## Screenshots to capture (Cmd+Shift+4), save in docs/screenshots/
1. `dashboard.png` - normal state, full page.
2. `change-guard.png` - after logic tamper: red bar, findings, ATT&CK chips, diff.
3. `alert-analysis.png` - alert card with Model analysis and ranked causes (live badge visible).
4. `incident-report.png` - the HTML report page.
5. `assistant.png` - "What does IL-04 do?" and the refusal of `stop P-201`.

## Devpost form (do last)
- [ ] Project name, tagline, track, description (reuse the README sections).
- [ ] Repository URL: https://github.com/Ar0umian/plantmind
- [ ] YouTube video URL.
- [ ] Nemotron / Token Factory usage text and feedback text.
- [ ] Images (screenshots above).
- [ ] Submit before the deadline; keep a screenshot of the confirmation.

## After submitting
- Winners are announced around 11 Jan 2027. Winners must verify identity and complete tax forms (non-US residents: W-8BEN).
