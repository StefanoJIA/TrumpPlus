from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

VALID_SOURCE_TYPES = {"original_link", "public_archive", "news_link", "official_doc", "manual_note"}
MAX_EXCERPT_CHARS = 500


def build_source(args: argparse.Namespace) -> dict:
    source = {
        "source_name": args.source_name or _prompt("source_name"),
        "source_url": args.source_url or _prompt("source_url"),
        "archive_url": args.archive_url or _prompt("archive_url", required=False),
        "retrieved_at": args.retrieved_at or datetime.now(timezone.utc).isoformat(),
        "short_excerpt": args.short_excerpt or _prompt("short_excerpt"),
        "source_type": args.source_type or _prompt("source_type"),
        "topic_hint": args.topic_hint or _prompt("topic_hint", required=False),
        "why_it_matters": args.why_it_matters or _prompt("why_it_matters", required=False),
        "operator_note": args.operator_note or _prompt("operator_note", required=False),
    }
    validate_source(source)
    return source


def validate_source(source: dict) -> None:
    required = ["source_name", "source_url", "short_excerpt", "source_type"]
    missing = [field for field in required if not source.get(field)]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")
    if source["source_type"] not in VALID_SOURCE_TYPES:
        raise ValueError(f"source_type must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}")
    if len(source["short_excerpt"]) > MAX_EXCERPT_CHARS:
        raise ValueError(f"short_excerpt must be <= {MAX_EXCERPT_CHARS} characters")
    lowered = " ".join([source.get("source_name", ""), source.get("source_url", ""), source.get("operator_note", "")]).lower()
    if "sample" in lowered or "fake" in lowered:
        raise ValueError("Do not use sample/fake data as real pilot input")
    if not source["source_url"].startswith(("http://", "https://")):
        raise ValueError("source_url must be an http(s) URL")


def write_input(source: dict, output_path: Path, append: bool = False) -> dict:
    payload = {"sources": []}
    if append and output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8-sig"))
    payload.setdefault("sources", []).append(source)
    payload["operator_checklist"] = checklist()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def checklist() -> list[str]:
    return [
        "Do not paste full posts, full articles, or large verbatim text.",
        "Do not fabricate source_url or archive_url.",
        "Do not use sample/fake data as real pilot content.",
        "This helper does not connect to the internet or fetch page content.",
        "All real sources must still pass SourceReviewItem and evidence review.",
        "Manual publish only; this helper does not publish or call platform APIs.",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create data/pilot/pilot_input.json from human-entered source metadata")
    parser.add_argument("--output", default="data/pilot/pilot_input.json")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--source-name")
    parser.add_argument("--source-url")
    parser.add_argument("--archive-url")
    parser.add_argument("--retrieved-at")
    parser.add_argument("--short-excerpt")
    parser.add_argument("--source-type", choices=sorted(VALID_SOURCE_TYPES))
    parser.add_argument("--topic-hint")
    parser.add_argument("--why-it-matters")
    parser.add_argument("--operator-note")
    parser.add_argument("--yes", action="store_true", help="Skip final interactive confirmation")
    args = parser.parse_args()

    print("Checklist before writing pilot input:")
    for item in checklist():
        print(f"- {item}")
    source = build_source(args)
    print(json.dumps(source, ensure_ascii=False, indent=2))
    if not args.yes:
        confirm = input("Write this source to pilot input? Type YES to continue: ").strip()
        if confirm != "YES":
            raise SystemExit("Cancelled.")
    payload = write_input(source, Path(args.output), append=args.append)
    print(json.dumps({"status": "written", "output": args.output, "source_count": len(payload["sources"])}, ensure_ascii=False, indent=2))


def _prompt(label: str, required: bool = True) -> str:
    value = input(f"{label}: ").strip()
    if required and not value:
        raise SystemExit(f"{label} is required")
    return value


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
