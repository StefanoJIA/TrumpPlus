from __future__ import annotations

from contextvars import ContextVar

from app.auth.context import CurrentUserContext


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
current_user_var: ContextVar[CurrentUserContext | None] = ContextVar("current_user", default=None)


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str | None:
    return request_id_var.get()


def set_current_user(user: CurrentUserContext) -> None:
    current_user_var.set(user)


def get_current_user_context() -> CurrentUserContext | None:
    return current_user_var.get()
