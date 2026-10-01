#!/usr/bin/env bash
# second-brain 本地备份（T031 本地部分）
# 远程异地同步：待服务器阶段与同厂对象存储一起配（本地已是密文，远端直接传即可）
#
# 产出（默认 server/data/backups/，形态见 research.md R8）：
#   db/db-YYYYmmdd-HHMM.dump.gpg   数据库全量（pg_dump -Fc → gpg AES-256）
#   storage-mirror/               原文件增量明文镜像（与源同信任域；删除同步生效 FR-011）
# 密钥文件：~/.config/second-brain/backup.key（仅本机 root 可读；务必另存一份到密码管理器！）
# 保留策略：最近 KEEP_DAYS 天（默认 14）
# 定时：cron 每日 03:17（安装方式见 README.md）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BK_DIR="${SECOND_BRAIN_BACKUP_DIR:-$ROOT/server/data/backups}"
KEEP_DAYS="${SECOND_BRAIN_BACKUP_KEEP_DAYS:-14}"
KEY_FILE="${SECOND_BRAIN_BACKUP_KEY:-$HOME/.config/second-brain/backup.key}"
STAMP="$(date +%Y%m%d-%H%M)"

if [ ! -f "$KEY_FILE" ]; then
  echo "[backup] 缺少密钥文件 $KEY_FILE（初始化方法见 deploy/backup/README.md）" >&2
  exit 1
fi
mkdir -p "$BK_DIR/db"

# 并发防撞（手动/定时/多会话同时触发）：拿不到锁则跳过
exec 9>"$BK_DIR/.lock"
if command -v flock >/dev/null && ! flock -n 9; then
  echo "[backup] 另一次备份正在运行，跳过"
  exit 0
fi

# 定时场景（SECOND_BRAIN_BACKUP_STALE_ONLY=1）：20 小时内已有备份则跳过，
# 用于"每日定时 + 开机补跑"两条 cron 互不重复（WSL/笔记本不常在线时的兜底）。
if [ "${SECOND_BRAIN_BACKUP_STALE_ONLY:-0}" = "1" ]; then
  newest="$(ls -1t "$BK_DIR/db"/*.gpg 2>/dev/null | head -1 || true)"
  if [ -n "$newest" ] && [ -n "$(find "$newest" -mmin -1200 2>/dev/null)" ]; then
    echo "[backup] 距上次备份不足 20 小时，跳过（STALE_ONLY）"
    exit 0
  fi
fi

encrypt() { # stdin → 指定 .gpg 文件
  gpg --batch --yes --quiet --symmetric --cipher-algo AES256 \
    --passphrase-file "$KEY_FILE" -o "$1"
}

echo "[backup] $(date '+%F %T') 数据库 dump …"
docker compose -f "$ROOT/deploy/docker-compose.yml" exec -T db \
  pg_dump -U secondbrain -Fc secondbrain | encrypt "$BK_DIR/db/db-$STAMP.dump.gpg"

echo "[backup] 原文件增量镜像（明文；远程阶段以密文上云——R8）…"
mkdir -p "$BK_DIR/storage-mirror"
rsync -a --delete "$ROOT/server/data/storage/" "$BK_DIR/storage-mirror/"

db_file="$BK_DIR/db/db-$STAMP.dump.gpg"
if [ ! -s "$db_file" ]; then echo "[backup] 数据库产物为空，失败：$db_file" >&2; exit 1; fi

echo "[backup] 清理超过 ${KEEP_DAYS} 天的旧数据库备份 …"
find "$BK_DIR/db" -name '*.gpg' -mtime "+$KEEP_DAYS" -delete

echo "[backup] 完成 $STAMP"
ls -lh "$db_file" | awk '{print "         db:   ", $5, $9}'
du -sh "$BK_DIR/storage-mirror" | awk '{print "         files:", $1, $2}'
