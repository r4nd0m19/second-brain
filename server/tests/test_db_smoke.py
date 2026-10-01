"""T013 DoD：pytest 可运行 + 测试库自动建/用/清（模型冒烟）。"""

from sqlalchemy import select

from app.models import Document, DocumentStatus, User


async def test_user_and_document_roundtrip(session) -> None:
    user = User(username="tester", password_hash="x")
    session.add(user)
    await session.flush()

    doc = Document(
        owner_user_id=user.id,
        name="样例.pdf",
        format="pdf",
        size_bytes=123,
        sha256="deadbeef",
        status=DocumentStatus.processing,
        original_path="tester/1/样例.pdf",
    )
    session.add(doc)
    await session.commit()

    got = await session.scalar(select(Document).where(Document.sha256 == "deadbeef"))
    assert got is not None
    assert got.status is DocumentStatus.processing
    assert got.owner_user_id == user.id
