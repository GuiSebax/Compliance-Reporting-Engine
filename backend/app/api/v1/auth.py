"""Authentication endpoints.

``/auth/login`` uses the standard OAuth2 "password" form
(``application/x-www-form-urlencoded`` with ``username``/``password``
fields) rather than a JSON body — this is what makes FastAPI's built-in
Swagger "Authorize" button work out of the box, and is the shape
``OAuth2PasswordBearer`` (used in ``app.api.deps``) expects to pair with.
``username`` is the user's email address.

``/auth/register`` exists purely so this portfolio project is runnable
end-to-end without a separate seeding step. It is intentionally left
open (no invite code, no admin approval) — acceptable for a demo/local
environment, and explicitly called out as such in the README; a real
deployment would gate or remove it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.db.repositories.user_repository import UserRepository
from app.infrastructure.db.session import get_db
from app.infrastructure.logging import get_logger
from app.infrastructure.security.jwt import create_access_token
from app.infrastructure.security.passwords import hash_password, verify_password
from app.schemas.auth import RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    user = UserRepository(db).get_by_email(form_data.username)

    if user is None or not verify_password(form_data.password, user.hashed_password):
        logger.warning("login_failed", email=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.id)
    logger.info("login_succeeded", user_id=user.id)
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_access_token_expire_minutes,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    repo = UserRepository(db)
    if repo.get_by_email(payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists."
        )
    user = repo.create(email=payload.email, hashed_password=hash_password(payload.password))
    db.commit()
    logger.info("user_registered", user_id=user.id)
    return UserResponse.model_validate(user)
