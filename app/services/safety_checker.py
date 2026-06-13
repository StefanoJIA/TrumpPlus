from typing import Any


class SafetyChecker:
    def review(
        self,
        ranked_posts: list[dict[str, Any]],
        script: dict[str, Any],
        visual_plan: dict[str, Any],
        fact_checks: list[dict[str, Any]],
        claims: list[dict[str, Any]] | None = None,
        evidence_packs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        claims = claims or []
        evidence_packs = evidence_packs or []
        rules = [
            self._rule(
                "excerpt_length_within_limit",
                all(len(post.get("short_excerpt", "")) <= 500 for post in ranked_posts),
                "blocking",
                "Stored excerpts must stay within the configured short excerpt limit.",
                {"max_excerpt_chars": 500, "lengths": [len(post.get("short_excerpt", "")) for post in ranked_posts]},
            ),
            self._rule(
                "source_url_present",
                all(bool(post.get("source_url")) for post in ranked_posts) and bool(script.get("sources")),
                "blocking",
                "Every exported item must include source URLs.",
                {"post_source_urls": [post.get("source_url") for post in ranked_posts], "script_sources": script.get("sources", [])},
            ),
            self._rule(
                "no_full_text_republication",
                all("SAMPLE FAKE POST:" in post.get("short_excerpt", "") or len(post.get("short_excerpt", "")) <= 280 for post in ranked_posts),
                "warning",
                "Avoid republishing full post text; use brief excerpts and summaries.",
                {"excerpt_lengths": [len(post.get("short_excerpt", "")) for post in ranked_posts]},
            ),
            self._rule(
                "no_fake_screenshot_language",
                "fake_screenshot" in visual_plan.get("prohibited", [])
                and not any(term in str(visual_plan).lower() for term in ["生成假截图", "fake screenshot", "fake_screenshot_request"]),
                "blocking",
                "Visual plan must not request fake Truth Social screenshots.",
                {"prohibited": visual_plan.get("prohibited", [])},
            ),
            self._rule(
                "no_voice_impersonation_instruction",
                "仿声" not in script.get("text", "") and "voice impersonation" not in str(visual_plan).lower(),
                "blocking",
                "The package must not instruct Trump voice impersonation.",
                {"script_checked": True},
            ),
            self._rule(
                "no_lip_sync_instruction",
                "口型" not in script.get("text", "") and "lip_sync" in visual_plan.get("prohibited", []),
                "blocking",
                "The package must not instruct lip-sync video.",
                {"prohibited": visual_plan.get("prohibited", [])},
            ),
            self._rule(
                "no_targeted_political_persuasion",
                not any(term in script.get("text", "") for term in ["支持", "投票给", "反对他", "动员"]),
                "blocking",
                "The script must not direct support, opposition, voting, or mobilization.",
                {"checked_terms": ["支持", "投票给", "反对他", "动员"]},
            ),
            self._rule(
                "claims_have_fact_check",
                self._claims_have_checks(claims, fact_checks),
                "blocking",
                "Claims requiring fact-checking must have fact-check records with sources.",
                {"claim_count": len(claims), "fact_check_count": len(fact_checks)},
            ),
            self._rule(
                "evidence_pack_present_for_claims",
                self._evidence_packs_present(claims, evidence_packs),
                "blocking",
                "Every generated claim must have an EvidencePack.",
                {"claim_count": len(claims), "evidence_pack_count": len(evidence_packs)},
            ),
            self._rule(
                "high_risk_claims_have_evidence",
                self._high_risk_claims_have_evidence(claims, evidence_packs),
                "blocking",
                "High-risk claims, especially accusations, require attached evidence before export.",
                {"high_risk_claims": self._high_risk_claims(claims), "evidence_packs": evidence_packs},
            ),
            self._rule(
                "evidence_pack_review_status",
                not any(pack.get("status") == "needs_review" for pack in evidence_packs),
                "warning",
                "Evidence packs marked needs_review should be resolved before publication.",
                {"needs_review": [pack for pack in evidence_packs if pack.get("status") == "needs_review"]},
            ),
            self._rule(
                "no_unverified_accusation",
                not any(
                    check.get("claim_type") == "accusation" and check.get("verdict") in {"unsupported", "unclear", "disputed"}
                    for check in fact_checks
                ),
                "blocking",
                "Unverified or disputed accusations cannot be exported.",
                {"accusation_checks": [check for check in fact_checks if check.get("claim_type") == "accusation"]},
            ),
            self._rule(
                "ai_visuals_labeled",
                all(card.get("ai_label") == "AI 生成示意图" for card in visual_plan.get("cards", [])),
                "blocking",
                "AI illustrative visuals must be labeled.",
                {"labels": [card.get("ai_label") for card in visual_plan.get("cards", [])]},
            ),
            self._rule(
                "human_review_required",
                True,
                "info",
                "Human review is required before export.",
                {"human_review_required": True},
            ),
        ]
        blocking_reasons = [rule["message"] for rule in rules if not rule["passed"] and rule["severity"] == "blocking"]
        warnings = [rule["message"] for rule in rules if not rule["passed"] and rule["severity"] == "warning"]
        if blocking_reasons:
            overall_status = "blocked"
        elif warnings:
            overall_status = "warning"
        else:
            overall_status = "passed"
        return {
            "overall_status": overall_status,
            "status": overall_status,
            "blocking_reasons": blocking_reasons,
            "warnings": warnings,
            "rules": rules,
            "checks": {rule["rule_id"]: rule["passed"] for rule in rules},
            "notes": blocking_reasons + warnings,
        }

    def _rule(self, rule_id: str, passed: bool, severity: str, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "passed": bool(passed),
            "severity": severity,
            "message": message,
            "evidence": evidence,
        }

    def _claims_have_checks(self, claims: list[dict[str, Any]], fact_checks: list[dict[str, Any]]) -> bool:
        checks_by_claim = {check.get("claim_id"): check for check in fact_checks}
        for claim in claims:
            if claim.get("requires_fact_check"):
                check = checks_by_claim.get(claim.get("id"))
                if not check:
                    return False
        return True

    def _evidence_packs_present(self, claims: list[dict[str, Any]], evidence_packs: list[dict[str, Any]]) -> bool:
        claim_ids = {claim.get("id") for claim in claims}
        pack_claim_ids = {pack.get("claim_id") for pack in evidence_packs}
        return claim_ids <= pack_claim_ids

    def _high_risk_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            claim
            for claim in claims
            if claim.get("claim_type") == "accusation"
            or any(term in str(claim.get("claim_text", "")).lower() for term in ["accuse", "fraud", "illegal", "crime", "corrupt"])
        ]

    def _high_risk_claims_have_evidence(self, claims: list[dict[str, Any]], evidence_packs: list[dict[str, Any]]) -> bool:
        packs_by_claim = {pack.get("claim_id"): pack for pack in evidence_packs}
        for claim in self._high_risk_claims(claims):
            pack = packs_by_claim.get(claim.get("id"))
            if not pack or int(pack.get("evidence_count") or 0) <= 0:
                return False
            if pack.get("verdict") in {"unsupported", "unclear"}:
                return False
        return True
