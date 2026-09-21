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


def create_user(db, username, password, role="member"):
    if (
        role not in ("admin", "member")
        or not 1 <= len(username) <= 80
        or len(password) < 12
        or len(password) > 1024
    ):
        raise ValueError(
            "username required; password 12..1024 characters; role admin/member"
        )
    user = User(username=username, password_hash=hasher.hash(password), role=role)
    db.add(user)
    db.commit()
    return user


def verify_login(db, username, password):
    user = db.scalar(select(User).where(User.username == username))
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid or not user or user.disabled:
        raise Problem(401, "invalid_credentials", "账号或密码错误")
    return user
