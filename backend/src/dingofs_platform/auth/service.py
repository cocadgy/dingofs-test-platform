import hashlib
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import select
from dingofs_platform.auth.models import User
from dingofs_platform.errors import Problem

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("not-a-real-login-password")


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    return digest(token + ":csrf")


def create_user(db, username, password, role="member", *, email):
    from .schemas import normalize_email

    email = normalize_email(email)
    if (
        role not in ("admin", "member")
        or not 1 <= len(username) <= 80
        or len(password) < 6
        or len(password) > 1024
    ):
        raise ValueError(
            "username required; password 6..1024 characters; role admin/member"
        )
    user = User(
        username=username, email=email, password_hash=hasher.hash(password), role=role
    )
    db.add(user)
    db.commit()
    return user


def password_matches(password_hash, password):
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_login(db, username, password):
    user = db.scalar(select(User).where(User.username == username))
    valid = password_matches(user.password_hash if user else DUMMY_HASH, password)
    if not valid or not user or user.disabled:
        raise Problem(401, "invalid_credentials", "账号或密码错误")
    return user
