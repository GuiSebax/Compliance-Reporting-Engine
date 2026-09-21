from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import User


class UserRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return self._session.scalar(stmt)

    def get_by_id(self, user_id: str) -> User | None:
        return self._session.get(User, user_id)

    def create(self, *, email: str, hashed_password: str) -> User:
        user = User(email=email.lower(), hashed_password=hashed_password)
        self._session.add(user)
        self._session.flush()
        return user
