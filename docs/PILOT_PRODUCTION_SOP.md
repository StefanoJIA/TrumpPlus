# Daily Truth Brief Pilot Production SOP

This SOP is for an internal pilot run that produces a manually reviewed video and pre-publish platform package. It does not publish content, does not crawl Truth Social, and does not create voice impersonation, lip-sync video, fake screenshots, or unauthorized news-image assets.

## 1. Daily Source Collection

1. Collect only public, compliant source leads from human-reviewed links, public archives, news links, official documents, or manual notes.
2. Do not log in to Truth Social, scrape it, bypass rate limits, bypass bot protections, or store large source-text mirrors.
3. Fill `data/pilot/pilot_input.json` from `data/pilot/pilot_input_template.json`.
4. Keep `short_excerpt` short. Do not paste full posts, full articles, or long copyrighted text.
5. Do not fabricate `source_url` or `archive_url`. Do not treat sample/fake data as real pilot data.

## 2. Source Review Standard

Every real source must enter `SourceReviewItem` before it can become evidence or a post.

Approve only when:
- The URL and archive URL are plausible and reviewable.
- The excerpt is short and human-entered.
- The source does not require prohibited scraping, login, CAPTCHA bypass, or Terms-of-Service circumvention.
- The source is not a fake screenshot or unauthorized image source.

Reject or mark needs changes when:
- The source is unverifiable.
- The excerpt is too long.
- The source appears fabricated.
- Terms status is blocked or unknown with unresolved risk.

## 3. Evidence Linking Standard

1. Promote approved sources to `EvidenceItem`.
2. Link approved evidence to claims using `ClaimEvidenceLink`.
3. Use `supports`, `disputes`, `contextualizes`, or `source_only` accurately.
4. Evidence suggestions are advisory only. They do not confirm facts or approve claims.
5. High-risk claims require explicit reviewer judgment, not blind auto-linking.

## 4. High-Risk Claim Handling

High-risk claims include accusations, legal claims, election claims, economy claims, and claims involving fraud, crime, courts, jobs, spending, or similar topics.

Rules:
- At least two evidence items are expected for high-risk factual claims.
- At least one evidence item should have `reliability_score >= 70`.
- Unsupported or unclear claims must remain qualified in script and platform copy.
- Do not write unsupported allegations as confirmed facts.

## 5. Brief Approval Standard

Before approving:
- Run evidence pack generation.
- Confirm `FactCheckQualityGate` is not `blocked`.
- Confirm all fact claims have approved evidence.
- Confirm safety review is not blocked.
- Confirm the same-user creator/approver policy is respected.

If the gate is blocked, request changes or block the brief. Do not render, export, or generate platform packages for blocked briefs.

## 6. Video QA Standard

Check:
- Final video exists and plays.
- Video contains information cards, source prompts, subtitles, and neutral narration or local stub audio.
- No Trump voice, political figure voice, celebrity voice, lip sync, or fake screenshot is present.
- AI illustrative visuals are labeled.
- No unauthorized news images are used.

## 7. Platform Copy QA Standard

Check:
- Titles are neutral and non-clickbait.
- Descriptions include source disclosure and AI/manual review disclosure.
- No platform package encourages voting, support, opposition, donation, targeting, or political mobilization.
- Unsupported or unclear claims are not written as confirmed conclusions.
- Package remains `manual_publish_only`.

## 8. Manual Publish Checklist

Before any human uploads outside this system:
- Re-open all source links and archive links.
- Compare the script against evidence and gate report.
- Inspect `final_video.mp4`.
- Inspect `platform_package.zip`.
- Confirm `editorial_qa_report.json` is `passed` or intentionally reviewed with documented revisions.
- Confirm no platform API was called by the system.

## 9. Blocked Handling

If a run is blocked:
- Do not publish or export as ready.
- Add stronger evidence or remove/qualify the claim.
- Re-run evidence pack and quality gate.
- Keep audit records intact.
- Do not bypass source review, evidence review, safety review, or human approval.

## 10. Standing Boundaries

- Manual publish only.
- No platform publishing API.
- No Truth Social direct scraper.
- No login-wall, CAPTCHA, anti-bot, or ToS bypass.
- No voice impersonation.
- No lip-sync video.
- No fake screenshots.
- No unauthorized news imagery.
