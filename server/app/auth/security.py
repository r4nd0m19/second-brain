"""密码哈希（argon2）与会话签名（itsdangerous）。"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

COOKIE_NAME = "sb_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 天

# 参数显式固化（审计二期 A1）：t=3 / m=64MiB / p=4 = RFC 9106 低内存档（OWASP 对照口径；
# 与 argon2-cffi 原默认一致，仅从"随库默认漂移"改为钉死；目标单次哈希 150-250ms）。
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
# 签名摘要显式 SHA-256（此前是 itsdangerous 默认 SHA-1；审计二期 A1）
_serializer = URLSafeTimedSerializer(
    settings.secret_key, salt="sb-session", signer_kwargs={"digest_method": hashlib.sha256}
)

# 登录对不存在的用户也跑一次校验，对齐耗时（防用户名枚举时序；审计二期 A1）——恒假
DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def make_session(user_id: str, epoch: int = 0) -> str:
    """会话 cookie 载荷：uid + 会话纪元（纪元不匹配 → 服务端判定失效，A1 吊销机制）。"""
    return _serializer.dumps({"uid": user_id, "ep": epoch})


def read_session(token: str | None) -> tuple[str, int] | None:
    """返回 (uid, epoch)；签名无效/过期/载荷不完整返回 None。"""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    ep = data.get("ep")
    if isinstance(uid, str) and isinstance(ep, int):
        return uid, ep
    return None
