"""SC-002：样例题集通过率验收（T032）——包裹 T040 的评测脚本（真实链路跑批）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.acceptance
async def test_sc002_sample_questions(client):
    """运行样例题集评测；要求命中率 ≥80%（脚本退出码 0）。"""
    docs = (await client.get("/api/documents")).json()
    indexed = [d for d in docs if d["status"] == "indexed"]
    if len(indexed) < 2:
        pytest.skip("库中已入库资料不足 2 份——先导入样本书再跑本题")

    proc = subprocess.run(
        [sys.executable, "tests/acceptance/sc002_eval.py"],
        capture_output=True,
        text=True,
        timeout=1200,
        cwd=SERVER_ROOT,
    )
    tail = proc.stdout[-1500:]
    assert proc.returncode == 0, f"SC-002 未达标：\n{tail}"
    assert "结论：PASS" in proc.stdout
