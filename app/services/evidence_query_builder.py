from __future__ import annotations

import json
from pathlib import Path

from app.models import Claim


class EvidenceQueryBuilder:
    def build(self, claim: Claim) -> list[str]:
        text = claim.claim_text.strip()
        neutral_text = self._neutralize(text, claim.claim_type)
        if claim.claim_type == "accusation":
            return [
                f"verify public record context {neutral_text}",
                f"official source court government statement {neutral_text}",
            ]
        return [
            f"official source {neutral_text}",
            f"public record background {neutral_text}",
        ]

    def write_queries(self, claims: list[Claim], output_dir: Path) -> Path:
        payload = [{"claim_id": claim.id, "claim_type": claim.claim_type, "queries": self.build(claim)} for claim in claims]
        path = output_dir / "search_queries.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _neutralize(self, text: str, claim_type: str) -> str:
        replacements = {
            "accuse": "claim about",
            "accuses": "claim about",
            "illegal": "legal status",
            "crime": "legal allegation",
            "fraud": "fraud allegation",
            "corrupt": "ethics allegation",
        }
        lowered = text
        for source, target in replacements.items():
            lowered = lowered.replace(source, target).replace(source.title(), target)
        if claim_type == "accusation":
            return f"neutral verification {lowered}"
        return lowered
