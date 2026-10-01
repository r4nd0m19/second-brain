"""原文件存储 —— 本地磁盘实现（可替换接口，constitution VII 底线 2）。

布局：storage/{owner}/{doc_id}/{原文件名}
语义：字节级保真（FR-013）—— 写入即原文，不做任何转换。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol

from app.config import settings


class BlobStore(Protocol):
    def save(self, owner: str, doc_id: str, filename: str, fileobj: BinaryIO) -> tuple[str, str, int]:
        """保存原文件，返回 (相对路径, sha256, 字节数)。"""

    def path(self, relative_path: str) -> Path: ...

    def delete(self, relative_path: str) -> None: ...

    def delete_document_dir(self, owner: str, doc_id: str) -> None: ...


def _sanitize_filename(name: str) -> str:
    """去除目录成分与危险字符，仅保留基本文件名（防路径穿越）。"""
    base = Path(name).name.strip()
    return base if base and base not in {".", ".."} else "file"


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, owner: str, doc_id: str) -> Path:
        return self.root / owner / doc_id

    def save(self, owner: str, doc_id: str, filename: str, fileobj: BinaryIO) -> tuple[str, str, int]:
        directory = self._doc_dir(owner, doc_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / _sanitize_filename(filename)

        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as out:
            while True:
                block = fileobj.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
                out.write(block)
        return str(target.relative_to(self.root)), digest.hexdigest(), size

    def path(self, relative_path: str) -> Path:
        full = (self.root / relative_path).resolve()
        if not full.is_relative_to(self.root.resolve()):  # 防越界读取
            raise ValueError("非法存储路径")
        return full

    def delete(self, relative_path: str) -> None:
        self.path(relative_path).unlink(missing_ok=True)

    def delete_document_dir(self, owner: str, doc_id: str) -> None:
        shutil.rmtree(self._doc_dir(owner, doc_id), ignore_errors=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def get_blob_store() -> LocalBlobStore:
    return LocalBlobStore(settings.storage_path)
