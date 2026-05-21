"""
core/auth.py — Authentication for Lex Kenya API

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP1 — SUPABASE (ACTIVE)
  Auth is handled entirely by the Supabase client in the React frontend.
  This backend only verifies the JWT that Supabase issues, using the
  project's JWT secret. No register/login endpoints needed here.

  Required .env vars:
    SUPABASE_JWT_SECRET   — Settings → API → JWT Settings → JWT Secret
    SUPABASE_URL          — Settings → API → Project URL  (frontend only)
    SUPABASE_ANON_KEY     — Settings → API → anon/public  (frontend only)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MVP2 — SELF-HOSTED JWT  (commented out below)
  When you outgrow Supabase or want zero vendor dependency, uncomment the
  MVP2 block and set ACTIVE_AUTH = "self_hosted" in .env.
  Users are stored as :User nodes in Neo4j. Passwords hashed with bcrypt.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel

from config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Auth"])

_bearer = HTTPBearer(auto_error=False)


# ══════════════════════════════════════════════════════════════════════════════
# MVP1 — SUPABASE JWT VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def _supabase_secret() -> str:
    s = get_settings()
    secret = getattr(s, "supabase_jwt_secret", "")
    if not secret:
        raise RuntimeError(
            "SUPABASE_JWT_SECRET is not set. "
            "Copy it from Supabase → Settings → API → JWT Settings."
        )
    return secret


class UserResponse(BaseModel):
    id: str
    email: str
    role: str = "authenticated"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency — decodes and validates a Supabase-issued JWT.
    Add  `Depends(get_current_user)`  to any route that requires login.
    Returns: { "id": str, "email": str, "role": str }
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — include an Authorization: Bearer <token> header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            _supabase_secret(),
            algorithms=["HS256"],
            # Supabase sets audience to "authenticated" for logged-in users
            options={"verify_aud": False},
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired — please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id: str = payload.get("sub", "")
    email: str = payload.get("email", "")
    role: str = payload.get("role", "authenticated")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing user id.",
        )

    return {"id": user_id, "email": email, "role": role}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the current authenticated user (from Supabase token)",
)
async def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """
    Convenience endpoint so the frontend can verify the token is accepted
    by the API. The real user profile lives in Supabase Auth.
    """
    return UserResponse(**current_user)


# ══════════════════════════════════════════════════════════════════════════════
# MVP2 — SELF-HOSTED JWT  (uncomment when migrating away from Supabase)
# ══════════════════════════════════════════════════════════════════════════════
#
# Steps to activate:
#   1. pip install python-jose[cryptography] passlib[bcrypt]
#   2. Set AUTH_JWT_SECRET and AUTH_TOKEN_EXPIRE_DAYS in .env
#   3. Uncomment everything below
#   4. Replace the get_current_user and /me above with the versions below
#   5. Register the /register and /login endpoints (they are already defined)
#
# ──────────────────────────────────────────────────────────────────────────────
#
# import uuid
# from datetime import datetime, timedelta, timezone
# from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
# from jose import JWTError, jwt
# from passlib.context import CryptContext
# from pydantic import BaseModel, EmailStr, Field
# from core.db import run_query
#
# ALGORITHM = "HS256"
# _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
#
#
# def _secret() -> str:
#     s = get_settings()
#     return getattr(s, "auth_jwt_secret", "lex-kenya-dev-secret-change-in-prod")
#
#
# def _expire_days() -> int:
#     s = get_settings()
#     return int(getattr(s, "auth_token_expire_days", 7))
#
#
# def _hash_password(plain: str) -> str:
#     return _pwd_context.hash(plain)
#
#
# def _verify_password(plain: str, hashed: str) -> bool:
#     return _pwd_context.verify(plain, hashed)
#
#
# def _create_token(user_id: str, email: str) -> str:
#     expire = datetime.now(timezone.utc) + timedelta(days=_expire_days())
#     return jwt.encode(
#         {"sub": user_id, "email": email, "exp": expire},
#         _secret(), algorithm=ALGORITHM,
#     )
#
#
# def _find_user_by_email(email: str) -> dict | None:
#     rows = run_query(
#         "MATCH (u:User {email: $email}) "
#         "RETURN u.id AS id, u.name AS name, u.email AS email, "
#         "u.password_hash AS password_hash",
#         {"email": email},
#     )
#     return rows[0] if rows else None
#
#
# def _create_user(user_id: str, name: str, email: str, password_hash: str) -> None:
#     run_query(
#         """
#         CREATE (u:User {
#             id: $id, name: $name, email: $email,
#             password_hash: $password_hash,
#             created_at: $created_at
#         })
#         """,
#         {
#             "id": user_id, "name": name, "email": email,
#             "password_hash": password_hash,
#             "created_at": datetime.now(timezone.utc).isoformat(),
#         },
#     )
#
#
# # Replace the Supabase get_current_user above with this one:
# async def get_current_user(
#     credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
# ) -> dict:
#     if credentials is None:
#         raise HTTPException(status_code=401, detail="Not authenticated",
#                             headers={"WWW-Authenticate": "Bearer"})
#     try:
#         payload = jwt.decode(credentials.credentials, _secret(),
#                              algorithms=[ALGORITHM])
#         email: str = payload.get("email", "")
#         if not email:
#             raise ValueError("missing email")
#     except (JWTError, ValueError) as exc:
#         raise HTTPException(status_code=401, detail="Invalid or expired token",
#                             headers={"WWW-Authenticate": "Bearer"}) from exc
#     user = _find_user_by_email(email)
#     if user is None:
#         raise HTTPException(status_code=401, detail="User not found")
#     return {"id": user["id"], "name": user["name"], "email": user["email"]}
#
#
# class RegisterRequest(BaseModel):
#     name: str = Field(..., min_length=1, max_length=100)
#     email: EmailStr
#     password: str = Field(..., min_length=8, max_length=128)
#
#
# class LoginRequest(BaseModel):
#     email: EmailStr
#     password: str = Field(..., min_length=1)
#
#
# class TokenResponse(BaseModel):
#     access_token: str
#     token_type: str = "bearer"
#
#
# @router.post("/register", response_model=TokenResponse, status_code=201)
# async def register(req: RegisterRequest) -> TokenResponse:
#     if _find_user_by_email(req.email):
#         raise HTTPException(status_code=409,
#                             detail="An account with this email already exists.")
#     user_id = str(uuid.uuid4())
#     try:
#         _create_user(user_id, req.name, req.email, _hash_password(req.password))
#     except Exception as exc:
#         logger.exception("Failed to create user in Neo4j")
#         raise HTTPException(status_code=500, detail="Could not create account.") from exc
#     logger.info("New user registered: %s", req.email)
#     return TokenResponse(access_token=_create_token(user_id, req.email))
#
#
# @router.post("/login", response_model=TokenResponse)
# async def login(req: LoginRequest) -> TokenResponse:
#     user = _find_user_by_email(req.email)
#     if user is None or not _verify_password(req.password, user["password_hash"]):
#         raise HTTPException(status_code=401, detail="Invalid email or password.",
#                             headers={"WWW-Authenticate": "Bearer"})
#     logger.info("User logged in: %s", req.email)
#     return TokenResponse(access_token=_create_token(user["id"], req.email))
#
#
# # Replace the Supabase /me above with this one:
# @router.get("/me", response_model=UserResponse)
# async def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
#     return UserResponse(**current_user)
#
# ══════════════════════════════════════════════════════════════════════════════
