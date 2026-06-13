# Daily Truth Brief

Daily Truth Brief is a compliant material-package and preview-video generator for neutral Chinese short-video briefs about public political social-media signals. It is not a reposting account, political propaganda tool, campaign persuasion tool, or automated publishing system.

Phase 2.8 adds a near-fully automated internal daily run that reads allowlisted feed JSON, fills review queues, suggests evidence, and can produce local/test preview video and platform packages while keeping final publishing manual. The system still does not auto-publish, scrape Truth Social, perform unbounded web crawling, clone voices, generate lip-sync video, create fake screenshots, or use unauthorized news images.

## Compliance Boundaries

- No direct login, scraping, crawling, or bulk collection from Truth Social.
- No bypassing anti-bot systems, CAPTCHA, login walls, rate limits, or terms of service.
- No large-scale full-text mirror of original posts.
- No Trump voice impersonation, political figure voice, celebrity voice, voice clone, or likeness-targeted TTS.
- No lip-sync video.
- No fake Truth Social screenshots or misleading social-media screenshot layouts.
- No unauthorized news photos.
- Visual assets must be self-made information cards and labeled `信息整理卡 / AI 生成示意图`.
- No automatic publishing. Human approval remains required before render/export workflows.
- No platform publishing API integration. Platform packages are manual pre-publish materials only.
- Every package keeps source references and safety review output.

This project organizes public information for neutral analysis. It does not ask audiences to support or oppose a candidate, party, policy action, or voting behavior.

## Local Startup

```bash
docker compose up --build -d
```

The API starts at `http://localhost:8015` on the host and listens on port `8000` inside the container.

Useful flow:

```bash
curl http://localhost:8015/health
curl -X POST http://localhost:8015/ingest/manual -H "Content-Type: application/json" -d '{"path":"data/sample_posts.json"}'
curl -X POST http://localhost:8015/sources/ingest/manual-url -H "Content-Type: application/json" -d '{"source_url":"https://example.org/manual/source-1","archive_url":"https://example.org/archive/source-1","source_name":"manual-editor-link","short_excerpt":"A human-provided excerpt for source review."}'
curl -X POST http://localhost:8015/editorial/topics/generate
curl -X POST http://localhost:8015/editorial/topics/1/select -H "Content-Type: application/json" -d '{"reviewer_name":"Editor","reviewer_note":"selected for neutral daily coverage"}'
curl -X POST http://localhost:8015/editorial/calendar/schedule -H "Content-Type: application/json" -d '{"topic_id":1,"reviewer_name":"Editor","reviewer_note":"scheduled by human editor"}'
curl -X POST http://localhost:8015/editorial/topics/1/generate-brief -H "Content-Type: application/json" -d '{"reviewer_name":"Editor","reviewer_note":"generate brief from selected topic"}'
curl -X POST http://localhost:8015/briefs/generate -H "Content-Type: application/json" -d '{"limit":3}'
curl -X POST http://localhost:8015/briefs/1/approve -H "Content-Type: application/json" -d '{"reviewer_name":"Editor","reviewer_note":"sources checked"}'
curl -X POST http://localhost:8015/briefs/1/evidence-pack/generate
curl -X POST http://localhost:8015/briefs/1/tts/generate -H "Content-Type: application/json" -d '{"provider":"local_stub","voice":"neutral_zh"}'
curl -X POST http://localhost:8015/briefs/1/render-package
curl -X POST http://localhost:8015/briefs/1/final-video
curl -X POST http://localhost:8015/briefs/1/platform-package
curl -OJ http://localhost:8015/briefs/1/final-video/download
curl -OJ http://localhost:8015/briefs/1/platform-package/download
python -m app.jobs.production_daily_run --dry-run
```

Review page:

```bash
open http://localhost:8015/briefs/1/review-page
open http://localhost:8015/editorial/console
open http://localhost:8015/editorial/briefs/1/production-console
open http://localhost:8015/sources/review-page
open http://localhost:8015/ops/dashboard
```

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

Tests use SQLite in memory for API coverage and validate generated JSON against schemas in `schemas/`.

## Phase 1.1 Review Workflow

- `app/config/source_policy.yaml` defines allowed, manual-review, and blocked sources plus excerpt/source-url rules.
- Unknown non-manual sources are blocked by default.
- Manual/sample data is allowed but stored with `source_review_required=true`.
- Safety review emits structured rules with `rule_id`, `passed`, `severity`, `message`, and `evidence`.
- Brief status supports `draft`, `needs_review`, `approved`, `blocked`, and `exported`.
- Review APIs support approve, block, request changes, and review report generation.
- Export API creates a zip package only after approval and only when safety is not blocked.

## Phase 1.2 Render Package

`POST /briefs/{id}/render-package` creates local production assets:

```text
exports/render_packages/brief_{id}/
  manifest.json
  script.txt
  subtitles.srt
  subtitles.json
  cover.png
  card_01_topic.png
  card_02_fact_check.png
  card_03_timeline.png
  card_04_sources.png
  sources.json
  safety_review.json
  README_RENDER.md
  readiness_report.json
```

The render manifest includes `brief_id`, `title`, `duration_target_seconds`, `aspect_ratio`, `script_segments`, `subtitle_items`, `visual_cards`, `source_cards`, `safety_labels`, and `output_files`.

`visual_cards` reserve Remotion-oriented fields: `scene_type`, `duration_seconds`, `image_path`, and `subtitle_range`.

## Phase 1.3 Final Video

`POST /briefs/{id}/final-video` renders a local MP4 only when:

- The brief is `approved`.
- `safety_review.overall_status` is not `blocked`.
- A generated render package exists.

Output directory:

```text
exports/final_videos/brief_{id}/
  final_video.mp4
  narration.txt
  narration_segments.json
  audio.wav
  tts_metadata.json
  render_report.json
  README_FINAL_VIDEO.md
```

The MP4 is produced by ffmpeg from PNG information cards, neutral local-stub audio, and `subtitles.srt`. The ffmpeg command creates a 9:16 1080x1920 preview with an audio track and burned-in subtitles.

## TTS Policy

Default provider: `app/tts/local_stub.py`.

- It does not call external APIs.
- It generates silent WAV audio for preview rendering.
- It writes `tts_metadata.json`.
- Allowed voice: `neutral_zh`.
- Blocked voice names include Trump, political figures, celebrities, clones, and impersonation intent.

`app/tts/openai_provider.py` is only a placeholder. Any future external provider must enforce neutral narrator voice only. Voice imitation is disallowed because it can mislead viewers about identity, endorsement, or authenticity.

## ffmpeg Rendering

`app/renderers/ffmpeg_renderer.py`:

- Reads `manifest.json`.
- Uses `narration.txt` and `narration_segments.json` from `AudioScriptBuilder`.
- Uses local-stub `audio.wav`.
- Displays each PNG card according to `manifest.visual_cards[].duration_seconds`.
- Burns in `subtitles.srt`.
- Writes `final_video.mp4` and `render_report.json`.

`app/renderers/ffmpeg_stub.py` remains a readiness checker for render packages.

## Phase 1.4 Platform Package

`POST /briefs/{id}/platform-package` creates a pre-publish package only when:

- The brief is `approved`.
- `safety_review.overall_status` is not `blocked`.
- A rendered `final_video.mp4` exists.

Output directory:

```text
exports/platform_packages/brief_{id}/
  final_video.mp4
  bilibili.json
  xiaohongshu.json
  douyin.json
  youtube_shorts.json
  qa_report.json
  copy_compliance_report.json
  sources.json
  safety_review.json
  MANUAL_PUBLISH_CHECKLIST.md
  README_PLATFORM_PACKAGE.md
  platform_package.zip
```

Each platform JSON includes at least three neutral title options, a description, pinned comment, tags, source disclosure, `AI 辅助整理 / 人工审核` disclosure, cover-selection guidance, and a manual publishing checklist.

### QA Gate

`app/services/video_qa_analyzer.py` uses `ffprobe` to inspect `final_video.mp4`:

- file size
- duration
- width and height
- video codec
- audio codec
- video/audio stream presence
- aspect ratio
- platform-specific fit warnings and blocking errors

Missing video or audio streams block the package. Duration or aspect-ratio mismatches are reported per platform so an editor can decide whether to revise the render before manual upload.

### Copy Compliance Checker

`app/services/compliance_copy_checker.py` blocks platform copy when it detects:

- targeted political persuasion
- missing sources
- missing AI/manual-review disclosure
- clickbait extreme terms such as `震惊`, `疯了`, `全网封杀`, or `彻底完了`
- unverified accusation wording
- voice impersonation claims
- missing manual-publish requirement

Generated copy is intentionally informational and neutral. It does not ask viewers to support or oppose any candidate, party, political action, or voting behavior.

### Manual Publish Only

This project does not integrate with Bilibili, Xiaohongshu, Douyin, YouTube, or any other platform publishing API. Political-content posting must remain a separate human decision after source review, safety review, video QA, copy compliance review, and platform policy review.

The system avoids automatic publishing because platform rules and political-content rules are context-sensitive, can change quickly, and require editorial judgment. Keeping this as a package generator prevents accidental political amplification and preserves human accountability.

## Phase 1.5 Source Review Workflow

Real source material must pass through the source review queue before it can enter brief generation:

```text
manual URL or public archive JSON
  -> SourceReviewItem
  -> human source review
  -> promote-to-post
  -> brief generation
```

`SourceReviewItem` stores only the review-safe fields needed for source triage: `source_url`, `archive_url`, `retrieved_at`, `adapter_name`, `terms_status`, `human_status`, short excerpt, normalized summary, media references, reviewer notes, and rejection reasons. It is intentionally separate from `Post` so unreviewed or blocked content cannot enter ranking, fact checking, script writing, rendering, or platform packaging.

### Manual URL Adapter

`POST /sources/ingest/manual-url` accepts a human-entered URL, optional archive URL, source name, and short excerpt. It does not fetch webpage HTML and does not save full article or post text.

```bash
curl -X POST http://localhost:8015/sources/ingest/manual-url \
  -H "Content-Type: application/json" \
  -d '{"source_url":"https://example.org/manual/source-1","archive_url":"https://example.org/archive/source-1","source_name":"manual-editor-link","short_excerpt":"Human-entered excerpt for review."}'
```

Manual URL items default to `terms_status=manual_review_required` and `human_status=pending`. Direct Truth Social domains are blocked and cannot be promoted.

### Public Archive JSON Adapter

`POST /sources/ingest/public-archive-json` reads a local JSON file such as `data/public_archive_sample.json`. It only accepts source names in `allowed_public_archives`, does not contact Truth Social, keeps original `source_url` and `archive_url`, truncates overlong excerpts, and writes warnings into item metadata.

```bash
curl -X POST http://localhost:8015/sources/ingest/public-archive-json \
  -H "Content-Type: application/json" \
  -d '{"path":"data/public_archive_sample.json"}'
```

### Source Review Page

Open:

```bash
open http://localhost:8015/sources/review-page
```

The page shows pending, needs-changes, and approved source items with source URL, archive URL, excerpt, terms status, warnings, and actions: approve, reject, needs changes, and promote.

### Promote-to-Post Rules

`POST /sources/review-queue/{id}/promote-to-post` is allowed only when:

- `human_status=approved`
- `terms_status` is not `blocked`
- reviewer note is provided

Rejected, blocked, pending, or needs-changes items cannot be promoted. Promote creates a `Post` with `source_policy.human_source_review_status=promoted`. Brief generation uses promoted posts plus explicit sample data only.

### Audit Log

Source ingest, approval, rejection, needs-changes, and promote-to-post actions write audit log rows with `entity_type`, `entity_id`, `action`, `actor`, `note`, and `created_at`. The single-item review API includes audit logs for that item.

Sample data remains available for tests and local demos, but real operation should not rely on `data/sample_posts.json`. Real sources must enter through source review and be promoted before brief generation.

## Phase 1.6 Evidence Pack

Phase 1.6 upgrades mock fact-checking into an explicit evidence layer:

```text
Claim
  -> EvidenceSource
  -> EvidenceItem
  -> EvidencePack
  -> FactCheck compatibility payload
  -> Safety review
  -> Evidence report
```

Evidence records store short excerpts, URLs, archive URLs, source metadata, summaries, confidence, editor notes, and verdicts. They do not store full-text mirrors.

### Evidence Providers

Provider interface: `app/evidence/base.py`.

Implemented providers:

- `manual`: attaches editor-provided evidence to a claim.
- `local_json`: reads local JSON evidence such as `data/sample_evidence.json`.
- `mock`: test-only placeholder.

Policy file: `app/config/evidence_policy.yaml`.

The policy defines allowlisted providers, blocked domains, maximum evidence excerpt length, minimum evidence expectations by claim type, and `production_disallow_mock_provider=true`. Unknown providers cannot run. The mock provider is blocked in production.

### Manual Evidence

```bash
curl -X POST http://localhost:8015/claims/1/evidence/manual \
  -H "Content-Type: application/json" \
  -d '{"source_name":"Manual official source","source_url":"https://example.org/evidence/1","publisher_type":"official","reliability_tier":"high","terms_status":"allowed","excerpt":"Short evidence excerpt.","supports_claim":"supports","confidence":0.9,"reviewer_note":"Checked by editor."}'
```

Blocked evidence domains such as direct Truth Social URLs are rejected. Evidence only stores short excerpts and metadata.

### Local JSON Evidence

```bash
curl -X POST http://localhost:8015/claims/1/evidence/from-json \
  -H "Content-Type: application/json" \
  -d '{"path":"data/sample_evidence.json"}'
```

The local JSON provider reads local structured evidence. It does not search the web or crawl pages.

### Verdict Rules

- `opinion`: `verdict=opinion`, evidence optional.
- supported evidence: `confirmed`.
- contradicting evidence: `disputed`.
- no evidence for factual/prediction/quote claims: `unclear`, `status=insufficient`.
- no evidence for accusation: `unsupported`, `status=insufficient`.
- contextual or unclear evidence: `needs_review`.

Fact-check JSON remains compatible with earlier phases, but its verdicts and sources now come from EvidencePack state.

### Safety Linkage

Safety review now includes evidence rules:

- every claim must have an EvidencePack;
- high-risk claims, especially accusations, require attached evidence;
- unsupported or unclear accusations are blocking;
- packs marked `needs_review` produce warnings.

This prevents unsupported accusations from entering export, render, final video, or platform packaging workflows.

### Evidence Reports

`POST /briefs/{id}/evidence-pack/generate` refreshes claim packs, fact-check payloads, safety review, and writes:

```text
exports/evidence_reports/brief_{id}/
  evidence_report.json
  evidence_report.md
  claims_matrix.csv
  sources.json
  README_EVIDENCE.md
```

`GET /briefs/{id}/evidence-pack/report` returns the generated JSON report.

Reports include claim text, claim type, verdict, evidence count, supporting/contradicting/context evidence, reliability tier, unresolved risks, and editor notes.

### Future Providers

Future NewsAPI, Tavily, GDELT, or similar providers may be added only behind provider policy, domain/source allowlists, excerpt limits, source review expectations, and human editorial review. They must not perform unbounded crawling, bypass terms, scrape Truth Social directly, or mirror full text.

## Phase 1.7 Production Runbook and Editorial Ops

Phase 1.7 introduces production controls for daily editorial operation without changing the core compliance boundaries.

### Production Policy

Policy file: `app/config/production_policy.yaml`.

Key defaults:

- `production_mode=true`
- `allow_sample_data=false`
- `disallow_mock_evidence=true`
- `require_source_review=true`
- `require_evidence_pack=true`
- `require_human_approval=true`
- `require_platform_manual_publish=true`
- `export_retention_days=30`
- `max_daily_briefs=1`
- `max_posts_per_brief=4`

Production mode excludes sample data unless explicit test mode is used. Mock evidence is never allowed in production because it can create false confidence in political claims. Auto approval is disabled because source review, evidence review, safety review, and final publishing judgment require a human editor.

### Daily Production Run

Dry run:

```bash
python -m app.jobs.production_daily_run --dry-run
```

Write run artifacts:

```bash
python -m app.jobs.production_daily_run --run
```

The production run:

- reads promoted posts only;
- excludes sample data in production mode;
- generates `topic_selection_report.json`;
- creates recommended editorial topics in `pending` or `needs_more_evidence` state;
- does not auto-select, auto-schedule, or auto-generate briefs from topics;
- never auto-approves;
- never renders final video automatically;
- never generates platform publishing packages automatically;
- never publishes to any platform.

Output directory:

```text
exports/production_runs/YYYY-MM-DD/
  run_report.json
  source_summary.json
  topic_selection_report.json
  topic_summary.json
  brief_summary.json
  blocking_reasons.json
  README_RUN.md
```

### Ops Dashboard

API:

```text
GET /ops/summary
GET /ops/queue-status
GET /ops/blocking-reasons
GET /ops/daily-runs
GET /ops/daily-runs/{date}
```

Page:

```text
GET /ops/dashboard
```

The dashboard shows source review queue, editorial topics, editorial calendar entries, evidence review queue, blocked safety items, briefs awaiting approval, final videos ready, platform packages ready, and daily run reports.

### Blocking Reason Report

`app/services/blocking_reason_aggregator.py` aggregates:

- source blocked
- evidence insufficient
- unsupported accusation
- safety blocked
- QA failed
- copy compliance failed

The same structure is written into production run `blocking_reasons.json` and served from `/ops/blocking-reasons`.

### Audit Export

Audit export:

```text
GET /ops/audit-log/export?format=json
GET /ops/audit-log/export?format=csv
```

The audit log includes source review actions, promote-to-post, evidence attach/review, brief approve/block, render package generation, final video rendering, and platform package generation.

### Cleanup Policy

Dry run:

```bash
python -m app.jobs.cleanup_exports --dry-run
```

Delete old export directories:

```bash
python -m app.jobs.cleanup_exports --run
```

Cleanup uses `production_policy.export_retention_days`. Dry run is the default operational posture; deletion requires the explicit `--run` flag.

### Production Non-Negotiables

Production operation still does not:

- scrape Truth Social directly;
- bypass anti-bot, CAPTCHA, login walls, or terms;
- run unbounded search/crawling;
- save full-text mirrors;
- use mock evidence;
- auto-approve political content;
- auto-render final videos without approval;
- auto-publish to Bilibili, Xiaohongshu, Douyin, YouTube, or any other platform.

## Phase 1.8 Neutral TTS and Voice QA

Phase 1.8 keeps `local_stub` as the default TTS provider and adds a gated optional `openai_tts` provider. Real TTS must be explicitly enabled and must pass Voice QA before final video rendering can use it.

### TTS Policy

Policy file: `app/config/tts_policy.yaml`.

Key defaults:

- `default_provider: local_stub`
- `allowed_providers: local_stub, openai_tts`
- `allow_external_tts: false`
- `allowed_voices: neutral_zh, neutral_zh_female, neutral_zh_male`
- blocked voice terms include Trump, Donald, president, celebrity, clone, impersonation, mimic, and imitation
- `require_voice_qa=true`
- `require_disclosure=true`

External TTS is blocked in production unless `allow_external_tts=true`. Voice names are allowlisted and checked for blocked terms before any provider runs.

### Generate TTS

```bash
curl -X POST http://localhost:8015/briefs/1/tts/generate \
  -H "Content-Type: application/json" \
  -d '{"provider":"local_stub","voice":"neutral_zh"}'
```

Status and download:

```text
GET /briefs/{id}/tts/status
GET /briefs/{id}/tts/download
POST /briefs/{id}/tts/voice-qa
```

TTS output directory:

```text
exports/tts/brief_{id}/
  narration.txt
  audio.wav or audio.mp3
  tts_metadata.json
  voice_qa_report.json
```

### Optional OpenAI TTS

`app/tts/openai_provider.py` supports an injectable client for tests and a real OpenAI SDK path for deployment. Tests do not call any external API.

To enable real TTS in a deployment:

```bash
export OPENAI_API_KEY=...
```

Then explicitly set `allow_external_tts=true` in `app/config/tts_policy.yaml`. The provider still accepts only neutral narrator voices from the allowlist.

### Voice QA

`app/services/voice_qa.py` checks:

- provider allowlist;
- voice allowlist;
- blocked voice terms;
- no identity imitation wording in metadata;
- disclosure presence;
- audio file existence;
- estimated/probed duration.

Voice QA returns `passed`, `warning`, or `blocked`. A blocked Voice QA report prevents final video generation.

### Final Video Audio Selection

Final video rendering uses:

1. generated TTS from `exports/tts/brief_{id}/` when Voice QA is not blocked;
2. otherwise local_stub audio generated during render.

The render report records `tts_source` and `voice_qa_status`.

### Why Voice Imitation Is Forbidden

Political figure or celebrity voice imitation can mislead viewers about identity, endorsement, authenticity, and authorship. This project only allows neutral narrator voices, never Trump, political figure, celebrity, cloned, or likeness-targeted voices. It also does not generate lip-sync video and does not imply that any public figure spoke the narration.

## Phase 1.9 Controlled External Evidence Search

Phase 1.9 adds a controlled search-provider boundary for evidence discovery. Search output is never treated as fact and never enters an EvidencePack directly.

```text
Claim
  -> neutral search query
  -> ExternalSearchProvider
  -> EvidenceCandidate
  -> human review
  -> accept candidate
  -> EvidenceSource + EvidenceItem
  -> EvidencePack
```

### External Search Policy

Policy file: `app/config/external_search_policy.yaml`.

Defaults:

- `allow_external_search=false`
- `allowed_providers=controlled_search,fake_search`
- `production_disallow_fake_search=true`
- domain allowlist and blocked-domain rules
- `max_results_per_claim`
- `max_excerpt_chars`
- `require_archive_url_when_available=true`
- `require_human_evidence_review=true`
- `disallow_truth_social_direct=true`

External search is off by default. In production, it must be explicitly enabled and must still respect domain policies, excerpt limits, and human evidence review.

### Providers

Provider interface: `app/external_search/base.py`.

Implemented providers:

- `controlled_search`: placeholder provider with optional injectable client for future NewsAPI, Tavily, GDELT, or similar APIs.
- `fake_search`: test-only provider; blocked in production.

Unknown providers are rejected. The first version does not require a real API key and does not perform unbounded crawling.

### Candidate Workflow

API:

```text
POST /claims/{claim_id}/evidence/search
GET /claims/{claim_id}/evidence/candidates
POST /evidence/candidates/{id}/accept
POST /evidence/candidates/{id}/reject
POST /evidence/candidates/{id}/block
```

Rules:

- search creates `EvidenceCandidate` only;
- pending candidates do not affect EvidencePack verdicts;
- accept requires `reviewer_name` and `reviewer_note`;
- accepted candidates create `EvidenceSource` and `EvidenceItem`;
- rejected or blocked candidates cannot enter evidence packs;
- blocked domains cannot be normalized into candidates;
- search actions and candidate review actions are written to audit log.

### Query Builder

`app/services/evidence_query_builder.py` creates neutral query suggestions. Accusation claims are rewritten with verification language such as neutral public-record context, instead of persuasive or inflammatory wording.

`POST /briefs/{id}/evidence-pack/generate` writes `search_queries.json` for claims that still lack evidence. It does not call external search unless `allow_search=true` and policy permits search.

### Why Search Results Are Not Evidence

Search snippets can be incomplete, stale, duplicated, out of context, or from unsuitable domains. For political content, treating snippets as facts would create avoidable misinformation risk. This project stores search results as review candidates first; only an editor-accepted candidate can become evidence.

Future NewsAPI, Tavily, GDELT, or similar providers belong behind `controlled_search` or another explicit provider, with allowlists, blocked-domain rules, excerpt limits, source review expectations, and human review. They must not scrape Truth Social directly, bypass access controls, mirror full text, or publish content automatically.

## Phase 2.0 Editorial Calendar and Daily Topic Selection

Phase 2.0 adds a human-gated editorial planning layer:

```text
promoted posts
  -> generated editorial topics
  -> human select / reject / needs more evidence
  -> optional calendar schedule
  -> human-triggered brief generation from selected topic
```

`EditorialTopic` stores date, title, summary, type, status, priority score, risk score, evidence score, platform fit score, selected post IDs, selected claim IDs, rationale, and editor note.

`EditorialCalendarEntry` stores date, topic, slot name, target platforms, planned duration, status, assigned editor, and publish-window note.

Topic statuses:

- `pending`
- `selected`
- `rejected`
- `needs_more_evidence`
- `scheduled`
- `used`

Calendar statuses:

- `draft`
- `ready_for_brief`
- `in_production`
- `completed`
- `canceled`

### Topic Selector

`app/services/topic_selector.py` reads promoted posts only. It merges similar topics, scores news value, evidence readiness, risk, platform fit, and freshness, then writes:

```text
exports/editorial_topics/YYYY-MM-DD/topic_selection_report.json
```

High-risk topics with insufficient evidence are marked `needs_more_evidence`. They cannot generate a brief until an editor resolves the evidence gap and changes the topic state.

The selector never auto-selects topics and never auto-generates briefs.

### Editorial APIs

```text
POST /editorial/topics/generate
GET /editorial/topics
GET /editorial/topics/{id}
POST /editorial/topics/{id}/select
POST /editorial/topics/{id}/reject
POST /editorial/topics/{id}/needs-more-evidence
POST /editorial/calendar/schedule
GET /editorial/calendar
GET /editorial/calendar/{date}
POST /editorial/topics/{id}/generate-brief
```

Select, reject, needs-more-evidence, schedule, and topic-brief generation require `reviewer_name` and `reviewer_note`.

Only `selected` or `scheduled` topics can generate a brief. `rejected` and `needs_more_evidence` topics are blocked. Briefs generated from a topic include `metadata_json.topic_id` and `metadata_json.calendar_entry_id`.

### Manual Topic Gate

The production daily run now recommends topics only. It does not select a topic, schedule a topic, generate a brief, approve a brief, render a final video, create a platform package, or publish. A human editor must explicitly advance each step.

Audit log actions include `topic_generated`, `topic_selected`, `topic_rejected`, `topic_needs_more_evidence`, `calendar_scheduled`, and `brief_generated_from_topic`.

## Phase 2.1 Editorial Review Console and One-click Production Flow

Phase 2.1 consolidates editorial operations into one console while keeping every compliance gate intact.

Pages:

```text
GET /editorial/console
GET /editorial/briefs/{id}/production-console
```

The unified console shows:

- Source Review Queue
- Topic Recommendations
- Editorial Calendar
- Briefs Needing Review
- Evidence Gaps
- Safety Blocks
- TTS / Voice QA
- Final Videos Ready
- Platform Packages Ready

The production console shows the full status chain:

```text
source_review
  -> topic_selected
  -> evidence_pack
  -> safety_review
  -> human_approval
  -> render_package
  -> tts
  -> voice_qa
  -> final_video
  -> platform_package
```

Each step shows status, blocking reasons, next allowed action, related artifact links, and audit timeline events.

### Next Action Service

`app/services/next_action_service.py` returns:

- `next_action`
- `allowed_actions`
- `blocked_actions`
- `blocking_reasons`
- `required_reviewer_note`
- `related_links`

Rules:

- unreviewed sources cannot enter brief generation;
- missing evidence packs must be generated before downstream production;
- safety blocked briefs cannot render;
- unapproved briefs cannot render final video or platform package;
- blocked Voice QA prevents final video;
- platform package remains manual publish only.

### One-click Production API

```text
POST /editorial/topics/{id}/start-production
GET /editorial/briefs/{id}/next-action
POST /editorial/briefs/{id}/run-next-step
```

`start-production` works only for `selected` or `scheduled` topics and still requires `reviewer_name` and `reviewer_note`.

`run-next-step` executes only the current allowed machine step:

- generate evidence pack
- generate render package
- generate neutral local-stub TTS
- generate final video
- generate platform package

It never auto-approves. When the next required step is human approval, it returns a blocking response telling the editor to use the explicit approval API with reviewer information. It never publishes and never calls platform publishing APIs.

### Timeline and Audit

```text
GET /editorial/briefs/{id}/timeline
GET /editorial/topics/{id}/timeline
GET /editorial/console/summary
```

`app/services/status_timeline_builder.py` combines current model status with `AuditLog` events, including source/topic/brief/render/final/platform actions where available.

Phase 2.1 does not weaken earlier gates. It is an operator console for human-reviewed production, not an automation tool for political publishing.

## Phase 2.2 Roles, Permissions, and Approval Policy

Phase 2.2 adds a minimal permission layer for multi-person editorial workflows.

### Auth Stub

Current user is read from request headers:

```text
X-User-Name: editor-a
X-User-Role: editor
X-Workspace-ID: 1
```

If headers are missing, the request is treated as `viewer` in the default workspace. `X-Workspace-ID` is optional for local/test; missing values use `daily-truth-brief-dev`.

This is a local or internal-network stub for MVP development. It is not a formal public authentication system, does not provide password/session security, and should be replaced with real auth before any public deployment.

### Roles

Model: `UserAccount`.

Roles:

- `admin`: all operations.
- `editor`: select topics, schedule calendar entries, generate briefs, request changes.
- `reviewer`: approve/block source review items, evidence, and briefs.
- `producer`: generate render packages, neutral TTS, final videos, and platform packages.
- `viewer`: read-only.

### Permission Matrix

`app/services/permission_service.py` exposes:

```text
can_review_source
can_select_topic
can_schedule_topic
can_generate_brief
can_review_evidence
can_approve_brief
can_render
can_generate_tts
can_generate_platform_package
can_export_audit
```

Denied writes return `403` and write a denied audit event where possible.

### Approval Policy

Policy file:

```text
app/config/approval_policy.yaml
```

Defaults:

- source review requires reviewer/admin;
- evidence review requires reviewer/admin;
- brief approval requires reviewer/admin;
- producer cannot approve briefs;
- same user cannot create and approve a brief unless admin;
- platform package requires approved brief;
- manual publish only remains true.

### Approval Records

Model: `ApprovalRecord`.

Critical source, evidence, topic, and brief decisions write structured approval records:

```text
entity_type
entity_id
action
actor
actor_role
decision
note
created_at
```

The production console displays current user, current role, permission status, and approval history. The editorial console shows current user/role and disables action controls for roles that cannot perform them.

### Non-negotiables

Phase 2.2 still does not:

- scrape Truth Social;
- bypass anti-bot, CAPTCHA, login walls, or terms;
- auto-approve;
- auto-publish;
- create voice impersonation, lip-sync video, fake screenshots, or unauthorized news-image packages.

Role permissions only narrow who can perform existing gated actions. They do not weaken source review, evidence review, safety review, human approval, Voice QA, or manual-publish requirements.

## Phase 2.3 Staging Security Hardening and Operational Invariants

Phase 2.3 prepares the app as an internal staging review tool. It does not add platform publishing, Truth Social scraping, voice impersonation, lip-sync video, fake screenshots, or unauthorized news-image workflows.

### Environment Safety

Environment variables:

```text
APP_ENV=local|test|staging|production
AUTH_MODE=header_stub|disabled|external
ALLOW_INSECURE_AUTH_STUB=false
```

Rules:

- `local` and `test` may use `AUTH_MODE=header_stub`.
- `staging` rejects `header_stub`; use `AUTH_MODE=external` with a real provider or the placeholder while wiring auth.
- `production` rejects `ALLOW_INSECURE_AUTH_STUB=true`.
- `production` rejects `AUTH_MODE=header_stub`.

The header auth stub is only for local/internal development. It is not a public internet authentication system.

### Security Health

```text
GET /health/security
```

Returns:

- `app_env`
- `auth_mode`
- `insecure_auth_stub`
- `manual_publish_only=true`
- `platform_publish_api_enabled=false`
- `truth_social_direct_scraper_enabled=false`
- dangerous config warnings
- permissions/source policy load status

### Request IDs

Middleware accepts or generates `X-Request-ID`. Every response includes `X-Request-ID`. Audit and approval records store the active request ID.

### Audit Hardening

`AuditLog` now stores:

- request ID
- actor name
- actor role
- before/after state hash fields
- immutable flag
- note and timestamp

Audit logs are exposed through read-only APIs. There is no update or delete API for audit rows.

```text
GET /admin/audit/{id}
GET /ops/audit-log/export?format=json
GET /ops/audit-log/export?format=csv
```

Audit export requires admin or reviewer. Individual admin audit read requires admin or reviewer.

### Permissions Matrix

```text
GET /admin/permissions/matrix
```

Admin only. The endpoint returns role/action allow-deny state and writes:

```text
docs/permissions_matrix.md
```

### Trace Manifests

Export package, render package, final video, and platform package now include `trace_manifest.json`.

Trace manifests include:

- package type
- workspace ID and workspace slug
- brief ID
- source review item IDs
- post IDs
- evidence IDs
- approval record IDs
- safety review ID
- producer/reviewer/generated_by
- generated time
- request ID
- compliance status
- `manual_publish_only=true`

### Operational Invariants

```text
GET /admin/invariants
```

Admin only. Checks include:

- unapproved brief cannot render/export;
- safety blocked cannot render/export/package;
- same user cannot create and approve;
- producer/editor cannot approve brief;
- platform package requires final video;
- manual publish only is true;
- no platform publish API is configured;
- no direct Truth Social scraper is enabled.

### Staging Smoke

```bash
python scripts/staging_smoke.py --base-url http://localhost:8015 --test-mode
```

The smoke flow checks health/security, current workspace, team visibility, invite create/revoke, permissions matrix, manual source intake, source review, promote-to-post, topic generation, topic select/schedule, start production, evidence pack, reviewer approval, producer render/TTS/final/platform package, audit export, and invariants.

It writes:

```text
staging_smoke_report.json
```

The smoke script is dry-run by design: it uploads nothing and publishes nothing.

## Phase 2.4 External Auth Readiness and Team Workspace

Phase 2.4 prepares the app for team operation and future external authentication. It does not connect Google OAuth, Auth0, Clerk, internal SSO, API-token auth, platform publishing APIs, or a Truth Social direct scraper.

### Workspace Model

New team models:

- `Workspace`: `name`, `slug`, `status`.
- `TeamMember`: user-to-workspace membership with role and status.
- `Invite`: pending/revoked/accepted/expired invitation placeholder with hashed token.
- `ApiToken`: inactive authentication placeholder with hashed token, scopes, and revoke state.

The default local/test workspace is:

```text
daily-truth-brief-dev
```

Header-stub users are automatically created or updated as `UserAccount` rows and bound to the current workspace as `TeamMember` rows.

### Current User Context

`app/auth/context.py` defines `CurrentUserContext`:

```text
user_id
user_name
role
workspace_id
auth_mode
is_authenticated
is_stub
request_id
```

Permission checks now consume this context rather than reading headers directly. Audit and approval records use the same context for actor, role, workspace ID, and request ID.

### Auth Providers

Provider interface:

```text
app/auth/providers/base.py
```

Implemented providers:

- `header_stub`: local/test only; reads `X-User-Name`, `X-User-Role`, and optional `X-Workspace-ID`.
- `external_placeholder`: configured placeholder for future OAuth/Auth0/Clerk/internal SSO work; it returns `501` until a real external provider is implemented.

`AUTH_MODE=header_stub` is intentionally blocked outside local/test. This prevents accidental staging or production exposure with trust-on-header authentication.

### Workspace APIs

```text
GET  /workspaces/current
GET  /workspaces/current/team
POST /workspaces/current/invites
POST /workspaces/current/invites/{id}/revoke
GET  /workspaces/current/audit-summary
POST /workspaces/current/api-tokens
POST /workspaces/current/api-tokens/{id}/revoke
```

Viewers can read the current workspace. Admins can view team membership, create/revoke invite placeholders, view audit summary, and create/revoke API-token placeholders. API tokens are not active authentication credentials yet.

### Workspace Isolation

Core resources now carry `workspace_id`:

- `SourceReviewItem`
- `Post`
- `BriefScript`
- `RenderPackage`
- `FinalVideo`
- `PlatformPackage`
- `AuditLog`
- `ApprovalRecord`

Query APIs default to the current workspace. Cross-workspace reads return `404`. Writes set `workspace_id` from `CurrentUserContext`. There is no cross-workspace superadmin mode in this phase.

### Trace and Audit

Trace manifests now include `workspace_id` and `workspace_slug`. Staging smoke reports include the workspace and current user context. Audit export is scoped to the current workspace and still contains request IDs, actor role, and hash fields.

### Still Manual Publish Only

Phase 2.4 is an auth-readiness and workspace-isolation phase. It still does not publish to Bilibili, Xiaohongshu, Douyin, YouTube, or any other platform. It still does not scrape Truth Social, generate voice impersonation, lip-sync video, fake screenshots, or unauthorized news images.

## Phase 2.5 Evidence-First Source Intake and Fact-Check Quality Gate

Phase 2.5 makes evidence coverage explicit before human approval. It does not add Truth Social scraping, platform publishing, voice impersonation, lip-sync video, fake screenshots, or unauthorized news images.

### Evidence-First Flow

```text
SourceReviewItem
  -> promote-to-evidence or promote-to-post-and-evidence
  -> EvidenceItem
  -> ClaimEvidenceLink
  -> EvidencePack / FactCheck
  -> FactCheckQualityGate
  -> human brief approval
  -> render/final/platform package
```

Approved source review items can now be promoted to evidence:

```text
POST /sources/review-queue/{id}/promote-to-evidence
POST /sources/review-queue/{id}/promote-to-post-and-evidence
```

Pending, rejected, or blocked source review items cannot become evidence. Evidence promotion writes audit and approval records with workspace ID, actor, role, request ID, and hash fields.

### Evidence Models

`EvidenceItem` now supports source-first evidence:

- `workspace_id`
- `source_review_item_id`
- optional `post_id` and `claim_id`
- `evidence_type`
- title/source URL/archive URL/excerpt
- `reliability_score`
- `terms_status`
- `human_status`
- creator/reviewer and timestamps

`ClaimEvidenceLink` connects approved evidence to claims with:

- `support_type`: `supports`, `disputes`, `contextualizes`, or `source_only`
- confidence: `low`, `medium`, or `high`
- editor note

### Evidence APIs

```text
GET  /evidence
GET  /evidence/{id}
POST /evidence/{id}/approve
POST /evidence/{id}/reject
POST /evidence/{id}/score
GET  /evidence/{id}/audit

POST   /claims/{id}/evidence-links
GET    /claims/{id}/evidence-links
DELETE /claims/{id}/evidence-links/{link_id}
```

Only approved evidence can be linked to a claim. Claims and evidence must belong to the same workspace.

### Fact-Check Quality Gate

Service:

```text
app/services/fact_check_quality_gate.py
```

The gate returns:

- `status`: `passed`, `warning`, or `blocked`
- claim coverage
- missing evidence claims
- weak evidence claims
- high-risk claims
- recommendations

Rules:

- opinion claims may pass without evidence, but must stay framed as opinion;
- factual claims without evidence block real brief approval;
- accusation/legal/election/economy high-risk claims need stronger coverage;
- high-risk claims require at least two evidence items and one reliability score of at least 70;
- manual-note-only evidence without an external link is a warning for low risk and blocking for high risk.

Sample/demo data remains available for local tests, but real promoted-source workflows should link approved evidence before approval.

### Brief, Script, Platform, and Trace

Brief approval runs the quality gate. If the gate is blocked, approval returns `409` and records the gate result.

`ScriptWriter` now maps verdicts conservatively:

- `confirmed`: may say public sources support the claim;
- `disputed`: must say the claim is disputed;
- `unsupported` or `unclear`: must say there is not enough public evidence;
- `opinion`: must be framed as political expression or opinion.

Platform packages include:

```text
evidence_summary.json
fact_check_quality_gate.json
```

Platform descriptions also remind reviewers that sources and evidence should be kept in the description or pinned comment. Trace manifests include `evidence_item_ids`, `claim_evidence_link_ids`, and `fact_check_quality_gate_status`.

This phase keeps the same hard boundaries: manual publish only, no platform publish API, no Truth Social direct scraper, no voice clone, no lip-sync, no fake screenshots, and no unauthorized news imagery.

## Phase 2.6 Pilot Production Run and Editorial QA

Phase 2.6 focuses on running a first compliant pilot sample instead of adding more low-level infrastructure. It uses human-prepared source input, source review, approved evidence, claim-evidence links, the fact-check quality gate, final video rendering, and platform packaging to produce a manual-publish-ready package.

It still does not publish to any platform, call platform publishing APIs, scrape Truth Social, bypass access controls, clone voices, generate lip-sync video, create fake screenshots, or use unauthorized news images.

### Pilot Input

Copy the template before a pilot:

```bash
cp data/pilot/pilot_input_template.json data/pilot/pilot_input.json
```

Each source entry includes:

- `source_name`
- `source_url`
- `archive_url`
- `retrieved_at`
- `short_excerpt`
- `source_type`
- `topic_hint`
- `why_it_matters`
- `operator_note`

Rules:

- Do not paste full posts, full articles, or large copyrighted text into `short_excerpt`.
- Keep excerpts within the configured short-excerpt limit.
- Do not fabricate source URLs or archive URLs.
- Do not use sample/fake data as real pilot input.
- Real sources must enter `SourceReviewItem` before becoming evidence or posts.

### Pilot Runner

Local/test example:

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

The runner performs:

```text
pilot input
  -> manual-url source intake
  -> source review queue
  -> optional local/test source approval
  -> promote-to-post-and-evidence
  -> topic/brief generation
  -> evidence linking suggestions
  -> optional local/test evidence linking
  -> evidence pack
  -> FactCheckQualityGate
  -> reviewer approval only if gate is not blocked
  -> render package
  -> final_video.mp4
  -> platform package
  -> pilot QA reports
```

`--auto-approve-sources-for-local-test` and `--auto-link-evidence-for-local-test` are refused outside `local` or `test` as reported by `/health/security`. Staging and production require explicit human review.

### Evidence Suggestions

`app/services/evidence_link_suggester.py` scores approved evidence against claim text and source excerpts. Suggestions include:

- `support_type`
- confidence
- score
- `requires_manual_confirmation`

Suggestions never approve evidence, never confirm facts, and are conservative for high-risk claims.

### Editorial QA Report

`app/services/editorial_qa_reporter.py` writes:

```text
exports/pilot_runs/brief_{id}/
  pilot_run_report.json
  editorial_qa_report.json
  PILOT_REPORT.md
```

The QA report includes evidence coverage, high-risk claims, unsupported or unclear claims, script risk notes, video files, platform copy status, manual publish checklist status, and `qa_status`.

Review pages expose the same Pilot QA state:

```text
GET /briefs/{id}/pilot-qa
GET /briefs/{id}/evidence-link-suggestions
```

### Pilot SOP

The editorial operating guide is in:

```text
docs/PILOT_PRODUCTION_SOP.md
```

It covers daily source collection, source review, evidence linking, high-risk claim handling, brief approval, video QA, platform copy QA, manual publishing checklist, and blocked-run handling.

### Why Manual Source Review Remains Required

Pilot production is meant to test the human editorial workflow with real but compliant inputs. Automated source collection would create avoidable risks around Terms of Service, anti-bot controls, copyrighted text retention, and political misinformation. Source review preserves provenance, operator accountability, and evidence traceability before any claim enters a brief.

## Phase 2.7 First Real Editorial Sample and Template Tuning

Phase 2.7 supports a first real internal sample by improving input preparation and QA around script readability, subtitle pacing, visual-card completeness, and publish readiness. It does not add publishing automation or direct source scraping.

### Create Pilot Input

Use:

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

The helper writes `data/pilot/pilot_input.json`, validates required fields and excerpt length, prints a checklist, and does not fetch webpages or connect to the internet. Editors must not paste large original text blocks, fabricate sources, or use sample data as real input.

### Video Template Config

Template knobs live in:

```text
app/config/video_template.yaml
```

It defines aspect ratio, resolution, target duration, card durations, subtitle max length, title/source card style, AI/manual-review labels, and source-number display.

### Script, Subtitle, and Visual QA

New QA services:

```text
app/services/script_readability_qa.py
app/services/subtitle_timing_qa.py
app/services/visual_template_qa.py
```

They check:

- long narration sentences;
- AI-like filler and sensational wording;
- unsupported/unclear claims written as fact;
- 45-90 second spoken length;
- subtitle length, duration, density, and empty subtitle lines;
- PNG card existence and resolution;
- AI/information-card labels, Daily Truth Brief project presence, source numbers, and sources card.

`editorial_qa_report.json` now includes:

```text
script_readability_report
subtitle_timing_report
visual_template_report
first_sample_publish_readiness
```

The review page displays readability score, subtitle timing status, visual template status, blockers, revision recommendations, and publish readiness. It still has no publish button.

### First Sample Checklist

Use:

```text
docs/FIRST_SAMPLE_CHECKLIST.md
```

This checklist covers manual source collection, `pilot_input.json`, `pilot_run.py`, final video review, platform package review, blocked conditions, Episode 0 internal sample criteria, and manual publishing criteria.

The standing boundaries remain unchanged: manual publish only, no platform publishing API, no direct Truth Social scraper, no voice impersonation, no lip sync, no fake screenshots, and no unauthorized news imagery.

## Phase 2.8 Near-Fully Automated Daily Run

Phase 2.8 adds an internal daily run for near-daily production. It reads allowlisted public archive/manual feed JSON or allowlisted public RSS/Atom/JSON feeds, creates source review items, ranks topics, suggests evidence links, and in local/test can generate a preview video and platform package. It still stops short of publishing and keeps final platform upload as a human decision.

### Daily Feed JSON

Default input:

```text
data/feeds/daily_truth_feed.json
```

Shape:

```json
{
  "feed_date": "2026-06-13",
  "items": [
    {
      "source_name": "sample-public-archive-json",
      "source_url": "https://example.org/source",
      "archive_url": "https://example.org/archive",
      "retrieved_at": "2026-06-13T12:00:00Z",
      "short_excerpt": "Short human-entered excerpt.",
      "source_type": "public_archive",
      "topic_hint": "Neutral topic hint",
      "why_it_matters": "Why it matters for neutral coverage.",
      "source_confidence": "medium"
    }
  ]
}
```

`app/sources/daily_feed_json.py` does not fetch webpages, does not log in, does not crawl Truth Social, and rejects non-allowlisted `source_name` values. Every item becomes a `SourceReviewItem` with `human_status=pending` unless the local/test orchestrator explicitly runs local-auto.

### Allowlisted Remote Feed

Optional remote/public feed config:

```text
app/config/remote_source_feeds.yaml
```

The remote feed adapter supports RSS, Atom, and JSON feed documents from explicitly allowlisted feed names:

```yaml
feeds:
  - name: sample-public-archive-json
    enabled: true
    feed_url: data/feeds/remote_feed_sample.xml
    parser: rss
    source_type: public_archive
    require_item_date_match: true
    date_window_days: 0
    require_topic_keyword_match: true
    topic_keywords:
      - trump
      - donald trump
      - truth social
    exclude_keywords:
      - sports
```

Run a remote-feed dry run:

```bash
python -m app.jobs.daily_run_orchestrator --date today --mode dry-run --feed-mode remote --feed app/config/remote_source_feeds.yaml
```

`app/sources/remote_feed.py` reads only the feed document. It does not fetch linked article pages, does not log in, does not bypass rate limits, and blocks direct `truthsocial.com` feed or item URLs. Each item is stored as a short-excerpt `SourceReviewItem` with `human_status=pending`, so a human reviewer still decides whether it can become evidence and enter the brief pipeline.

Before using a real public feed, run the readiness gate:

```bash
python -m app.jobs.daily_run_orchestrator --feed-mode remote --feed app/config/remote_source_feeds.yaml --check-feed-readiness
```

Or through the API:

```text
POST /sources/remote-feed/readiness
```

The readiness report checks allowlist membership, blocked domains, direct Truth Social URLs, parser support, preview item URLs, short excerpt availability, and whether items will enter `SourceReviewItem` instead of bypassing review. A blocked readiness report stops remote daily-run intake before any source review items are created.

For daily production, configure freshness and topical filters:

- `require_item_date_match=true` keeps only items whose feed timestamp falls within `date_window_days` of the run date.
- `require_topic_keyword_match=true` keeps only items whose title, excerpt, summary, or URL contains a configured topic keyword.
- `exclude_keywords` removes known off-topic feed entries before source review intake.

The adapter records `filter_report` in API responses and `feed_filter_report` in daily run reports, including raw item count, kept item count, date-filtered count, topic-filtered count, and exclusion-filtered count.

### Orchestrator

Dry run:

```bash
python -m app.jobs.daily_run_orchestrator --date today --mode dry-run
```

Remote-feed dry run:

```bash
python -m app.jobs.daily_run_orchestrator --date today --mode dry-run --feed-mode remote --feed app/config/remote_source_feeds.yaml
```

Local/test auto run:

```bash
python -m app.jobs.daily_run_orchestrator --date today --mode local-auto
```

Flow:

```text
daily feed
  -> source review queue
  -> optional local/test source approve
  -> promote-to-post-and-evidence
  -> topic generation
  -> auto topic selection guard
  -> brief generation
  -> evidence link suggestions
  -> optional local/test evidence links
  -> FactCheckQualityGate
  -> optional local/test reviewer approval
  -> render package
  -> final_video.mp4
  -> platform package
  -> daily_run_report
```

Output:

```text
exports/daily_runs/{date}/
  daily_run_report.json
  DAILY_RUN_REPORT.md
exports/daily_runs/index.json
exports/daily_runs/latest.json
```

Each daily run refreshes `index.json` and `latest.json`. These files summarize recent runs, latest `final_video_path`, latest `platform_package_path`, manual action count, blockers, warnings, and the standing compliance flags.

### Modes

- `dry-run`: ingests feed items into review queue and reports manual actions. It does not approve sources, approve briefs, render, generate platform packages, or publish.
- `local-auto`: allowed only when `/health/security` reports `APP_ENV=local` or `APP_ENV=test`. It can auto-approve local/test sources, auto-link low-risk evidence suggestions, approve if FactCheckQualityGate passes, render video, and generate platform package.
- staging/production: `local-auto` is rejected. Human reviewers must approve sources, evidence, and briefs. Final publish remains outside the system.

### Manual Actions Queue

Endpoints:

```text
GET /daily-runs
GET /daily-runs/latest
GET /daily-runs/{date}/summary
GET /daily-runs/{date}/manual-actions
GET /daily-runs/{date}/page
```

Manual actions include:

- sources needing review;
- evidence needing review;
- claims needing evidence;
- briefs needing approval;
- final packages needing human publish decision.

The daily run page has no publish button.

`GET /daily-runs/latest` is the quickest way for an operator or dashboard to find the newest run, whether it stopped at source review, produced a local/test preview video, or generated a manual platform package.

### Scheduled Dry Run

Scheduler environment variables:

```text
DAILY_RUN_ENABLED=false
DAILY_RUN_MODE=dry-run
DAILY_RUN_HOUR=8
```

The scheduler is disabled by default. Even when enabled, it cannot publish. `DAILY_RUN_MODE=local-auto` is forbidden in staging/production.

### Auto Topic Selection Guard

`app/services/auto_topic_selector.py` scores source count, evidence strength, public importance, scriptability, risk level, and novelty. High-risk weak-evidence topics are blocked; opinion-only/no-evidence topics are downranked.

Remote-feed daily run reports include `feed_readiness`. This is intended for real operations where the source feed may change or be reconfigured; the report makes unsafe configuration visible before the pipeline can generate brief/video/package artifacts.

Daily run reports also include `feed_filter_report`, so editors can see whether a quiet day means there were no feed items, no same-day items, no Trump-related items, or only excluded/off-topic entries.

### Why Boundaries Remain

The daily run is an internal production accelerator, not a publishing robot or scraper. Direct Truth Social scraping, login-wall bypass, large text mirrors, automated platform posting, political voice imitation, lip sync, fake screenshots, and unauthorized news images remain prohibited.

## Remotion Stub

`remotion/README.md` and `remotion/sample_manifest.json` document how a later Remotion template can consume the same manifest. Future source adapters must use a source allowlist, adapter-level terms checks, no direct Truth Social scraping, and human source review before material enters the pipeline.

## JSON Schemas

- `video_asset.schema.json`
- `safety_review.schema.json`
- `brief_export.schema.json`
- `render_manifest.schema.json`

## Daily Dry Run

```bash
python -m app.jobs.daily_brief --dry-run
```

The dry run reads sample/manual data, generates a brief, and prints brief ID, status, top posts, and safety status. It does not export, render MP4, or publish.

## Why There Is No Truth Social Direct Scraper

Direct scraping would create avoidable legal, terms-of-service, anti-bot, login-wall, and data-retention risks. This project accepts only compliant manual or public-archive inputs and keeps a source adapter boundary for future compliant sources. Any future adapter must pass `validate_terms_safety()` and source-policy checks before data can enter the pipeline.
