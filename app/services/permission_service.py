from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.current_user import CurrentUser
from app.core.request_context import get_request_id
from app.models import ApprovalRecord, AuditLog, BriefScript


class PermissionService:
    def __init__(self, policy_path: str | Path = "app/config/approval_policy.yaml") -> None:
        self.policy = yaml.safe_load(Path(policy_path).read_text(encoding="utf-8"))

    def can_review_source(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "reviewer"})

    def can_select_topic(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "editor"})

    def can_schedule_topic(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "editor"})

    def can_generate_brief(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "editor"})

    def can_review_evidence(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "reviewer"})

    def can_approve_brief(self, user: CurrentUser) -> bool:
        if self.policy.get("producer_cannot_approve_brief") and user.role == "producer":
            return False
        return self._role_in(user, {"admin", "reviewer"})

    def can_render(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "producer"})

    def can_generate_tts(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "producer"})

    def can_generate_platform_package(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "producer"})

    def can_export_audit(self, user: CurrentUser) -> bool:
        return self._role_in(user, {"admin", "reviewer"})

    def matrix(self) -> dict[str, dict[str, bool]]:
        actions = {
            "review_source": self.can_review_source,
            "select_topic": self.can_select_topic,
            "schedule_topic": self.can_schedule_topic,
            "generate_brief": self.can_generate_brief,
            "review_evidence": self.can_review_evidence,
            "approve_brief": self.can_approve_brief,
            "render": self.can_render,
            "generate_tts": self.can_generate_tts,
            "generate_platform_package": self.can_generate_platform_package,
            "export_audit": self.can_export_audit,
        }
        matrix: dict[str, dict[str, bool]] = {}
        for role in ["admin", "editor", "reviewer", "producer", "viewer"]:
            user = CurrentUser(
                user_id=None,
                user_name=f"matrix_{role}",
                display_name=role,
                role=role,
                workspace_id=1,
                workspace_slug="daily-truth-brief-dev",
                auth_mode="header_stub",
                is_authenticated=True,
                is_stub=True,
                request_id=None,
            )
            matrix[role] = {name: fn(user) for name, fn in actions.items()}
        return matrix

    def write_matrix_doc(self, path: Path = Path("docs/permissions_matrix.md")) -> Path:
        matrix = self.matrix()
        path.parent.mkdir(parents=True, exist_ok=True)
        actions = list(next(iter(matrix.values())).keys())
        lines = ["# Permissions Matrix", "", "| Role | " + " | ".join(actions) + " |", "|---|" + "|".join(["---"] * len(actions)) + "|"]
        for role, permissions in matrix.items():
            values = ["allow" if permissions[action] else "deny" for action in actions]
            lines.append("| " + role + " | " + " | ".join(values) + " |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def assert_allowed(
        self,
        db: Session,
        user: CurrentUser,
        allowed: bool,
        action: str,
        *,
        entity_type: str = "system",
        entity_id: int = 0,
    ) -> None:
        if allowed:
            return
        db.add(
            AuditLog(
                entity_type=entity_type,
                entity_id=entity_id,
                workspace_id=user.workspace_id,
                action=f"{action}_denied",
                actor=user.username,
                actor_name=user.username,
                actor_role=user.role,
                request_id=user.request_id or get_request_id(),
                immutable=True,
                note=f"role={user.role}",
            )
        )
        db.commit()
        raise HTTPException(status_code=403, detail=f"Role {user.role} is not allowed to perform {action}")

    def assert_not_same_creator(self, user: CurrentUser, brief: BriefScript) -> None:
        if not self.policy.get("same_user_cannot_create_and_approve_brief"):
            return
        creator = (brief.metadata_json or {}).get("created_by")
        if creator and creator == user.username and user.role != "admin":
            raise HTTPException(status_code=403, detail="same_user_cannot_create_and_approve_brief")

    def record_approval(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: int,
        action: str,
        user: CurrentUser,
        decision: str,
        note: str | None,
    ) -> None:
        db.add(
            ApprovalRecord(
                entity_type=entity_type,
                entity_id=entity_id,
                workspace_id=user.workspace_id,
                action=action,
                actor=user.username,
                actor_role=user.role,
                decision=decision,
                request_id=user.request_id or get_request_id(),
                note=note,
            )
        )

    def _role_in(self, user: CurrentUser, roles: set[str]) -> bool:
        return user.is_active and user.role in roles
