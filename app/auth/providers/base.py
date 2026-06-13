from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import Request
from sqlalchemy.orm import Session

from app.auth.context import CurrentUserContext


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, request: Request, db: Session) -> CurrentUserContext:
        raise NotImplementedError

    @abstractmethod
    def validate_environment(self) -> None:
        raise NotImplementedError
