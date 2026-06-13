from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, EditorialTopic, EvidencePack, Post


class TopicSelector:
    risk_terms = {
        "accuse",
        "accusation",
        "fraud",
        "illegal",
        "crime",
        "criminal",
        "lawsuit",
        "court",
        "election",
        "corrupt",
        "指控",
        "违法",
        "犯罪",
        "选举",
        "法院",
        "腐败",
    }

    def generate_topics(
        self,
        db: Session,
        *,
        topic_date: date | None = None,
        output_dir: Path | None = None,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        target_date = topic_date or date.today()
        posts = [
            post
            for post in db.scalars(select(Post).order_by(Post.published_at.desc())).all()
            if post.source_policy.get("human_source_review_status") == "promoted"
            and (workspace_id is None or post.workspace_id == workspace_id)
        ]
        groups = self._group_posts(posts)
        created_topics: list[EditorialTopic] = []
        recommendations = []
        for key, group_posts in groups.items():
            topic = self._build_topic(db, target_date, key, group_posts, workspace_id=workspace_id)
            db.add(topic)
            db.flush()
            created_topics.append(topic)
            recommendations.append(self.topic_payload(topic))
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": target_date.isoformat(),
            "input_promoted_posts": len(posts),
            "topic_count": len(created_topics),
            "auto_selected": False,
            "automatic_brief_generation": False,
            "recommendations": recommendations,
            "blocking_reasons": [
                {
                    "topic_id": item["id"],
                    "status": item["status"],
                    "reasons": item["rationale"].get("blocking_reasons", []),
                }
                for item in recommendations
                if item["status"] == "needs_more_evidence"
            ],
        }
        report_path = self._write_report(report, output_dir)
        return {"topics": created_topics, "report": report, "report_path": str(report_path)}

    def topic_payload(self, topic: EditorialTopic) -> dict[str, Any]:
        return {
            "id": topic.id,
            "date": topic.date.isoformat(),
            "title": topic.title,
            "summary": topic.summary,
            "topic_type": topic.topic_type,
            "status": topic.status,
            "priority_score": topic.priority_score,
            "risk_score": topic.risk_score,
            "evidence_score": topic.evidence_score,
            "platform_fit_score": topic.platform_fit_score,
            "selected_post_ids": topic.selected_post_ids,
            "selected_claim_ids": topic.selected_claim_ids,
            "rationale": topic.rationale,
            "editor_note": topic.editor_note,
            "created_at": topic.created_at.isoformat() if topic.created_at else None,
            "updated_at": topic.updated_at.isoformat() if topic.updated_at else None,
        }

    def _group_posts(self, posts: list[Post]) -> dict[str, list[Post]]:
        groups: dict[str, list[Post]] = defaultdict(list)
        for post in posts:
            key = self._topic_key(post)
            groups[key].append(post)
        return dict(groups)

    def _topic_key(self, post: Post) -> str:
        base = post.topic or post.summary or post.short_excerpt
        words = re.findall(r"[a-z0-9\u4e00-\u9fff]+", base.lower())
        return " ".join(words[:6]) or f"post-{post.id}"

    def _build_topic(self, db: Session, target_date: date, key: str, posts: list[Post], workspace_id: int | None = None) -> EditorialTopic:
        post_ids = [post.id for post in posts]
        claims = list(db.scalars(select(Claim).where(Claim.post_id.in_(post_ids))).all()) if post_ids else []
        selected_claim_ids = [claim.id for claim in claims]
        evidence_score = self._evidence_score(db, claims)
        risk_score = self._risk_score(posts, claims)
        platform_fit_score = self._platform_fit(posts)
        news_value = self._news_value(posts)
        freshness = self._freshness(posts)
        priority_score = round(
            news_value * 0.35 + evidence_score * 0.25 + platform_fit_score * 0.20 + freshness * 0.20 - risk_score * 0.15,
            4,
        )
        blocking_reasons = []
        status = "pending"
        if risk_score >= 0.65 and evidence_score < 0.60:
            status = "needs_more_evidence"
            blocking_reasons.append("high_risk_topic_requires_stronger_evidence_before_brief")
        title = self._title(posts, key)
        return EditorialTopic(
            workspace_id=workspace_id,
            date=target_date,
            title=title,
            summary=self._summary(posts),
            topic_type="public_post_cluster",
            status=status,
            priority_score=priority_score,
            risk_score=risk_score,
            evidence_score=evidence_score,
            platform_fit_score=platform_fit_score,
            selected_post_ids=post_ids,
            selected_claim_ids=selected_claim_ids,
            rationale={
                "news_value": news_value,
                "evidence_readiness": evidence_score,
                "risk": risk_score,
                "platform_fit": platform_fit_score,
                "freshness": freshness,
                "merged_post_count": len(posts),
                "merge_key": key,
                "blocking_reasons": blocking_reasons,
                "manual_selection_required": True,
            },
        )

    def _title(self, posts: list[Post], key: str) -> str:
        topic = posts[0].topic.strip() if posts and posts[0].topic else key
        return f"公开发帖议题：{topic[:80]}"

    def _summary(self, posts: list[Post]) -> str:
        excerpts = [post.summary or post.short_excerpt for post in posts]
        return "；".join(excerpts)[:1000]

    def _news_value(self, posts: list[Post]) -> float:
        scores = [post.ranking_score for post in posts if post.ranking_score is not None]
        if scores:
            return round(min(1.0, sum(scores) / len(scores)), 4)
        return 0.7 if len(posts) > 1 else 0.6

    def _evidence_score(self, db: Session, claims: list[Claim]) -> float:
        if not claims:
            return 0.45
        packs = list(db.scalars(select(EvidencePack).where(EvidencePack.claim_id.in_([claim.id for claim in claims]))).all())
        if not packs:
            return 0.35
        reviewed = [pack for pack in packs if pack.evidence_count > 0 and pack.status in {"ready", "reviewed"}]
        return round(len(reviewed) / max(1, len(packs)), 4)

    def _risk_score(self, posts: list[Post], claims: list[Claim]) -> float:
        text = " ".join([post.summary + " " + post.short_excerpt for post in posts] + [claim.claim_text for claim in claims]).lower()
        hits = sum(1 for term in self.risk_terms if term in text)
        accusation_claims = sum(1 for claim in claims if claim.claim_type == "accusation")
        return min(1.0, 0.15 + hits * 0.15 + accusation_claims * 0.25)

    def _platform_fit(self, posts: list[Post]) -> float:
        text_len = sum(len(post.summary or post.short_excerpt) for post in posts)
        if 80 <= text_len <= 900:
            return 0.85
        return 0.65

    def _freshness(self, posts: list[Post]) -> float:
        if not posts:
            return 0.0
        now = datetime.now(timezone.utc)
        latest = max(post.published_at for post in posts)
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - latest).total_seconds() / 3600)
        if age_hours <= 24:
            return 1.0
        if age_hours <= 72:
            return 0.75
        return 0.45

    def _write_report(self, report: dict[str, Any], output_dir: Path | None) -> Path:
        root = output_dir or Path("exports/editorial_topics") / report["date"]
        root.mkdir(parents=True, exist_ok=True)
        path = root / "topic_selection_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
