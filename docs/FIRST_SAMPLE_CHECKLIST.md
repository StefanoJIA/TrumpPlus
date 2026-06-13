# First Real Internal Sample Checklist

This checklist guides production of the first internal Daily Truth Brief sample. The system remains manual publish only and does not scrape Truth Social, call platform publishing APIs, clone voices, create lip-sync video, generate fake screenshots, or use unauthorized news imagery.

## 1. Collect Sources Manually

- Use only public, compliant links reviewed by a human editor.
- Do not log in to Truth Social through this system.
- Do not scrape, crawl, bypass CAPTCHA, bypass login walls, bypass rate limits, or ignore terms of service.
- Do not paste full posts or full articles into the app.
- Record source URL, archive URL if available, retrieved time, and a short excerpt.

## 2. Create `pilot_input.json`

Use the helper:

```bash
python scripts/create_pilot_input.py \
  --source-name "Reviewed public source" \
  --source-url "https://example.org/source" \
  --archive-url "https://example.org/archive/source" \
  --short-excerpt "Short human-entered excerpt only." \
  --source-type public_archive \
  --topic-hint "Neutral topic hint" \
  --why-it-matters "Why this matters for neutral public information review." \
  --operator-note "Human source review note." \
  --yes
```

The helper does not connect to the internet and does not fetch webpage content.

## 3. Run Pilot Production

Local/test only:

```bash
python scripts/pilot_run.py \
  --base-url http://localhost:8015 \
  --input data/pilot/pilot_input.json \
  --workspace daily-truth-brief-dev \
  --editor-name PilotEditor \
  --reviewer-name PilotReviewer \
  --producer-name PilotProducer \
  --auto-approve-sources-for-local-test \
  --auto-link-evidence-for-local-test
```

In staging/production, do not use auto-approve or auto-link flags. Human reviewers must approve sources and evidence links.

## 4. Review Outputs

Inspect:

- `exports/final_videos/brief_{id}/final_video.mp4`
- `exports/platform_packages/brief_{id}/platform_package.zip`
- `exports/pilot_runs/brief_{id}/pilot_run_report.json`
- `exports/pilot_runs/brief_{id}/editorial_qa_report.json`
- `exports/pilot_runs/brief_{id}/PILOT_REPORT.md`

## 5. Check Script, Subtitle, and Visual QA

The editorial QA report must include:

- `script_readability_report`
- `subtitle_timing_report`
- `visual_template_report`
- `first_sample_publish_readiness`

Review long sentences, unsupported-claim language, subtitle density, PNG card resolution, AI labels, project name, source numbers, and source card presence.

## 6. Must Block

Block the sample if:

- Source provenance is unclear or fabricated.
- FactCheckQualityGate is blocked.
- A factual claim lacks approved evidence.
- A high-risk claim has insufficient evidence.
- The script states unsupported or unclear claims as fact.
- Visuals contain fake screenshots, lip-sync, voice impersonation, or unauthorized news images.
- Platform copy contains political mobilization or missing source/AI disclosure.

## 7. Suitable for Episode 0 Internal Sample

The sample can be used internally when:

- Sources were manually entered and reviewed.
- Evidence links exist for factual claims.
- Safety and quality gates are not blocked.
- `final_video.mp4` plays correctly.
- Platform package exists and remains manual publish only.
- Editorial QA may still have non-blocking revision notes.

## 8. Suitable for Manual Publishing

Manual publishing may be considered only when:

- `first_sample_publish_readiness.ready_manual_publish` is true.
- Human reviewer reopens source links and archive links.
- Video, subtitles, visual cards, and platform copy are checked.
- Source disclosure and AI/manual-review disclosure remain visible.
- No platform API is used by this system.
