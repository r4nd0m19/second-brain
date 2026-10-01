"""T009 DoD：存 / 取 / 删 与 sha256 校验测试（原文件字节级保真，FR-013）。"""

import hashlib
import io
from pathlib import Path

import pytest

from app.storage.local import LocalBlobStore, sha256_file


def test_save_read_delete_roundtrip(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    payload = "第二大脑 original bytes ✓".encode()

    rel, digest, size = store.save("owner1", "doc1", "测试文件.pdf", io.BytesIO(payload))

    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert digest == sha256_file(store.path(rel))

    assert store.path(rel).read_bytes() == payload  # 字节级保真

    store.delete(rel)
    assert not store.path(rel).exists()


def test_filename_sanitized_no_traversal(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    rel, _, _ = store.save("o", "d", "../../evil.txt", io.BytesIO(b"x"))
    assert ".." not in rel
    assert store.path(rel).is_relative_to(tmp_path.resolve())


def test_path_escape_raises(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    with pytest.raises(ValueError):
        store.path("../outside.txt")


def test_delete_document_dir(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    store.save("o", "d", "a.txt", io.BytesIO(b"a"))
    store.delete_document_dir("o", "d")
    assert not (tmp_path / "o" / "d").exists()
