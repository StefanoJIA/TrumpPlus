from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evidence.manual_provider import ManualEvidenceProvider


class LocalJsonEvidenceProvider(ManualEvidenceProvider):
    provider_name = "local_json"

    def search_evidence(self, claim: Any, **kwargs: Any) -> list[dict[str, Any]]:
        path = Path(kwargs["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("evidence", [])
        if kwargs.get("claim_id") is not None:
            records = [record for record in records if record.get("claim_id") in {None, kwargs["claim_id"]}]
        return [self.normalize_evidence(record) for record in records]
