"""原文件存储 —— 本地磁盘实现（可替换接口，constitution VII 底线 2）。

布局：storage/{owner}/{doc_id}/{原文件名}
语义：字节级保真（FR-013）—— 写入即原文，不做任何转换。
F2 扩展：页面快照固定名 snapshot.html.gz（上传已是 gzip 则原样保存，否则落盘即压缩）。
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol

from app.config import settings

SNAPSHOT_NAME = "snapshot.html.gz"


class BlobStore(Protocol):
    def save(self, owner: str, doc_id: str, filename: str, fileobj: BinaryIO) -> tuple[str, str, int]:
        """保存原文件，返回 (相对路径, sha256, 字节数)。"""

    def save_snapshot(self, owner: str, doc_id: str, fileobj: BinaryIO) -> tuple[str, int]:
        """保存页面快照，返回 (相对路径, 存储字节数)。"""

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

    def save_snapshot(self, owner: str, doc_id: str, fileobj: BinaryIO) -> tuple[str, int]:
        """保存页面快照（.html 或 .html.gz，按魔数判定）；覆盖更新同名文件。"""
        directory = self._doc_dir(owner, doc_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / SNAPSHOT_NAME

        head = fileobj.read(2)
        is_gzip = head == b"\x1f\x8b"
        with target.open("wb") as out:
            if is_gzip:  # 已是 gzip：原样落盘（扩展端已压缩，省一次转码）
                if head:
                    out.write(head)
                while block := fileobj.read(1024 * 1024):
                    out.write(block)
            else:
                with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
                    if head:
                        gz.write(head)
                    while block := fileobj.read(1024 * 1024):
                        gz.write(block)
        return str(target.relative_to(self.root)), target.stat().st_size

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
