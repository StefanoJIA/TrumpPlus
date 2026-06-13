from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path


class EvidenceReportBuilder:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("exports/evidence_reports")

    def build(self, brief_payload: dict) -> dict:
        brief_id = brief_payload["id"]
        output_dir = self.base_dir / f"brief_{brief_id}"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        report = self._report_payload(brief_payload)
        json_path = output_dir / "evidence_report.json"
        md_path = output_dir / "evidence_report.md"
        csv_path = output_dir / "claims_matrix.csv"
        sources_path = output_dir / "sources.json"
        readme_path = output_dir / "README_EVIDENCE.md"

        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._markdown(report), encoding="utf-8")
        self._write_csv(report, csv_path)
        sources_path.write_text(json.dumps(report["sources"], ensure_ascii=False, indent=2), encoding="utf-8")
        readme_path.write_text(self._readme(brief_id), encoding="utf-8")
        return {
            "output_dir": str(output_dir),
            "evidence_report_path": str(json_path),
            "markdown_path": str(md_path),
            "claims_matrix_path": str(csv_path),
            "sources_path": str(sources_path),
            "readme_path": str(readme_path),
            "report": report,
        }

    def _report_payload(self, brief_payload: dict) -> dict:
        packs_by_claim = {pack["claim_id"]: pack for pack in brief_payload.get("evidence_packs", [])}
        rows = []
        source_map = {}
        for claim in brief_payload.get("claims", []):
            pack = packs_by_claim.get(claim["id"], {})
            evidence_items = pack.get("evidence_items", [])
            for item in evidence_items:
                source = item["source"]
                source_map[source["source_url"]] = source
            rows.append(
                {
                    "claim_id": claim["id"],
                    "claim": claim["claim_text"],
                    "claim_type": claim["claim_type"],
                    "verdict": pack.get("verdict", "missing"),
                    "status": pack.get("status", "missing"),
                    "evidence_count": pack.get("evidence_count", 0),
                    "supports": [item for item in evidence_items if item["supports_claim"] == "supports"],
                    "contradicts": [item for item in evidence_items if item["supports_claim"] == "contradicts"],
                    "contextual": [item for item in evidence_items if item["supports_claim"] in {"contextual", "unclear"}],
                    "reliability_tiers": sorted({item["source"]["reliability_tier"] for item in evidence_items}),
                    "unresolved_risks": self._risks(claim, pack),
                    "editor_notes": [item.get("reviewer_note") for item in evidence_items if item.get("reviewer_note")],
                    "rationale": pack.get("rationale"),
                }
            )
        return {
            "brief_id": brief_payload["id"],
            "title": brief_payload["title"],
            "claims": rows,
            "sources": list(source_map.values()),
            "summary": {
                "claim_count": len(rows),
                "needs_review": sum(1 for row in rows if row["status"] == "needs_review"),
                "insufficient": sum(1 for row in rows if row["status"] == "insufficient"),
                "disputed": sum(1 for row in rows if row["verdict"] == "disputed"),
            },
        }

    def _risks(self, claim: dict, pack: dict) -> list[str]:
        risks = []
        if not pack:
            risks.append("missing_evidence_pack")
        if pack.get("status") in {"insufficient", "needs_review", "blocked"}:
            risks.append(f"pack_status:{pack.get('status')}")
        if claim.get("claim_type") == "accusation" and pack.get("verdict") in {"unsupported", "unclear", "disputed"}:
            risks.append("accusation_not_confirmed")
        return risks

    def _write_csv(self, report: dict, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["claim_id", "claim_type", "verdict", "status", "evidence_count", "reliability_tiers", "unresolved_risks"],
            )
            writer.writeheader()
            for row in report["claims"]:
                writer.writerow(
                    {
                        "claim_id": row["claim_id"],
                        "claim_type": row["claim_type"],
                        "verdict": row["verdict"],
                        "status": row["status"],
                        "evidence_count": row["evidence_count"],
                        "reliability_tiers": "|".join(row["reliability_tiers"]),
                        "unresolved_risks": "|".join(row["unresolved_risks"]),
                    }
                )

    def _markdown(self, report: dict) -> str:
        lines = ["# Evidence Report", "", f"Brief ID: {report['brief_id']}", f"Title: {report['title']}", ""]
        for row in report["claims"]:
            lines.extend(
                [
                    f"## Claim {row['claim_id']}",
                    "",
                    row["claim"],
                    "",
                    f"- Type: {row['claim_type']}",
                    f"- Verdict: {row['verdict']}",
                    f"- Status: {row['status']}",
                    f"- Evidence count: {row['evidence_count']}",
                    f"- Reliability: {', '.join(row['reliability_tiers']) or 'none'}",
                    f"- Risks: {', '.join(row['unresolved_risks']) or 'none'}",
                    f"- Rationale: {row['rationale']}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _readme(self, brief_id: int) -> str:
        return "\n".join(
            [
                "# Daily Truth Brief Evidence Pack",
                "",
                "This report stores short evidence excerpts, source URLs, metadata, summaries, verdicts, and editor notes only. It is not a full-text mirror.",
                "",
                "No Truth Social scraping, no unbounded web crawling, and no automatic publishing are performed.",
                "",
                f"Brief ID: {brief_id}",
            ]
        )
