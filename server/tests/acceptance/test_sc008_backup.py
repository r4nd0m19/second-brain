"""SC-008：备份恢复演练验收（T032）——包裹 deploy/backup/restore.sh drill。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent


@pytest.mark.acceptance
def test_sc008_restore_drill():
    """运行一次完整恢复演练（解密 → 恢复库 → 行数/指纹/文件 sha256 对照）。"""
    if not shutil.which("docker"):
        pytest.skip("无 docker，跳过备份演练")
    drill = REPO_ROOT / "deploy" / "backup" / "restore.sh"
    if not drill.exists():
        pytest.skip("restore.sh 不存在")

    proc = subprocess.run(
        ["bash", str(drill), "drill"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, f"恢复演练失败：\n{proc.stdout[-2000:]}\n{proc.stderr[-500:]}"
    assert "恢复演练通过" in proc.stdout
    assert "❌" not in proc.stdout, "演练输出中存在失败项"
