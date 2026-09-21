"""Declarative base shared by every ORM model, and by Alembic's autogenerate."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
