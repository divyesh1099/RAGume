import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Profile, User, UserSession

SESSION_COOKIE_NAME = "rr_session"
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 260_000


@dataclass
class AuthSession:
    user: User
    session: UserSession


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return normalized


def normalize_full_name(full_name: str) -> str:
    cleaned = " ".join(full_name.strip().split())
    if not cleaned:
        raise HTTPException(status_code=422, detail="Full name cannot be empty.")
    if len(cleaned) > 120:
        raise HTTPException(status_code=422, detail="Full name must be 120 characters or fewer.")
    return cleaned


def validate_password(password: str) -> str:
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    return password


def _password_digest(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return digest.hex()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = _password_digest(password, salt)
    return f"{PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        iterations_str, salt, expected = password_hash.split("$", maxsplit=2)
        iterations = int(iterations_str)
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(digest, expected)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cleanup_expired_sessions(session: Session) -> None:
    now = utcnow()
    session.execute(delete(UserSession).where(UserSession.expires_at.is_not(None), UserSession.expires_at < now))


def create_user(session: Session, full_name: str, email: str, password: str) -> User:
    normalized_name = normalize_full_name(full_name)
    normalized_email = normalize_email(email)
    validate_password(password)

    existing = session.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    user_count = session.scalar(select(func.count(User.id))) or 0
    user = User(
        full_name=normalized_name,
        email=normalized_email,
        password_hash=hash_password(password),
    )
    session.add(user)
    session.flush()

    if user_count == 0:
        unowned_profiles = list(session.scalars(select(Profile).where(Profile.user_id.is_(None))).all())
        for profile in unowned_profiles:
            profile.user_id = user.id

    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session: Session, email: str, password: str) -> User:
    normalized_email = normalize_email(email)
    user = session.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return user


def create_user_session(session: Session, user: User) -> tuple[UserSession, str]:
    cleanup_expired_sessions(session)
    raw_token = secrets.token_urlsafe(32)
    expires_at = utcnow() + dt.timedelta(days=SESSION_TTL_DAYS)
    user_session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=expires_at,
    )
    session.add(user_session)
    session.commit()
    session.refresh(user_session)
    return user_session, raw_token


def get_authenticated_session(session: Session, token: str | None) -> AuthSession:
    cleanup_expired_sessions(session)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    token_hash = hash_session_token(token)
    record = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if record is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    expires_at = ensure_utc(record.expires_at)
    if expires_at is not None and expires_at < utcnow():
        session.delete(record)
        session.commit()
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    user = session.get(User, record.user_id)
    if user is None:
        session.delete(record)
        session.commit()
        raise HTTPException(status_code=401, detail="Authentication required.")

    record.last_seen_at = utcnow()
    session.commit()
    session.refresh(record)
    return AuthSession(user=user, session=record)


def get_current_user_from_request(session: Session, request: Request) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    auth_session = get_authenticated_session(session, token)
    return auth_session.user


def revoke_session(session: Session, token: str | None) -> None:
    if not token:
        return
    token_hash = hash_session_token(token)
    record = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if record is None:
        return
    session.delete(record)
    session.commit()
