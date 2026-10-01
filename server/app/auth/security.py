"""密码哈希（argon2）与会话签名（itsdangerous）。"""

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

COOKIE_NAME = "sb_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 天

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="sb-session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def make_session(user_id: str) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session(token: str | None) -> str | None:
    """返回 uid；签名无效或过期返回 None。"""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, str) else None
