"""T005 DoD：采集凭据生成 / 校验 / 吊销拒绝 / prefix 单测（含 DB 校验路径）。"""

from datetime import datetime, timezone

import pytest

from app.capture.security import (
    CaptureTokenError,
    generate_token,
    hash_token,
    verify_capture_token,
)
from app.models import CaptureToken, User


def test_generate_token_shape_and_uniqueness() -> None:
    token, prefix, digest = generate_token()
    assert token.startswith("sb_cap_")
    assert prefix == token[: len("sb_cap_") + 8]
    assert digest == hash_token(token)

    token2, _, digest2 = generate_token()
    assert token != token2
    assert digest != digest2


async def test_verify_ok_then_revoked_then_scope(session) -> None:
    user = User(username="cap-tester", password_hash="x")
    session.add(user)
    await session.flush()

    token, prefix, digest = generate_token()
    row = CaptureToken(owner_user_id=user.id, name="Windows Chrome", prefix=prefix, token_hash=digest)
    session.add(row)
    await session.commit()

    # 通过：last_used_at 被写入
    got = await verify_capture_token(session, token)
    assert got.id == row.id
    assert got.last_used_at is not None

    # 吊销后拒绝
    row.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    with pytest.raises(CaptureTokenError) as exc_info:
        await verify_capture_token(session, token)
    assert exc_info.value.kind == "invalid"

    # scope 不符
    other_token, other_prefix, other_digest = generate_token()
    session.add(
        CaptureToken(
            owner_user_id=user.id,
            name="other",
            prefix=other_prefix,
            token_hash=other_digest,
            scope="other",
        )
    )
    await session.commit()
    with pytest.raises(CaptureTokenError) as exc_info2:
        await verify_capture_token(session, other_token)
    assert exc_info2.value.kind == "scope"
