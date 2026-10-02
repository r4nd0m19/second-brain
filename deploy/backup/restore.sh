#!/usr/bin/env bash
# second-brain 恢复工具（T031）：从备份恢复数据库/原文件；支持完整恢复演练（SC-008）
#
# 备份形态（research.md R8）：
#   数据库 = 加密 dump（.gpg，需密钥/含解密链路）
#   原文件 = 增量明文镜像（storage-mirror/，与源同信任域）
#
# 用法：
#   restore.sh drill               完整演练：最近备份 → 恢复 → 全量对照，输出 ✅/❌
#   restore.sh db <dump.gpg> [库名]  恢复数据库（默认 secondbrain_restore；灾难恢复用 secondbrain）
#   restore.sh files [目标目录]      把原文件镜像同步到目标目录（默认 server/data/restore-drill）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BK_DIR="${SECOND_BRAIN_BACKUP_DIR:-$ROOT/server/data/backups}"
KEY_FILE="${SECOND_BRAIN_BACKUP_KEY:-$HOME/.config/second-brain/backup.key}"
DB_USER=secondbrain
LIVE_DB=secondbrain

dc() { docker compose -f "$ROOT/deploy/docker-compose.yml" "$@"; }
q() { dc exec -T db psql -U "$DB_USER" -d "$1" -tAc "$2"; }
decrypt() { gpg --batch --yes --quiet --decrypt --passphrase-file "$KEY_FILE" "$1"; }
latest() { ls -1t "$BK_DIR/$1"/*.gpg 2>/dev/null | head -1; }

restore_db() { # $1=加密dump  $2=目标库
  local target="$2"
  echo "[restore] 恢复数据库 → $target …"
  q postgres "DROP DATABASE IF EXISTS $target;" >/dev/null
  q postgres "CREATE DATABASE $target;" >/dev/null
  decrypt "$1" | dc exec -T db pg_restore -U "$DB_USER" -d "$target" --no-owner
  echo "[restore] 数据库恢复完成：$target"
}

restore_files() { # $1=目标目录（镜像 → 目录，镜像语义：目标多余文件会被删除）
  mkdir -p "$1"
  rsync -a --delete "$BK_DIR/storage-mirror/" "$1/"
  echo "[restore] 原文件已同步到：$1"
}

drill_once() {
  local dump target=secondbrain_restore tmp="$ROOT/server/data/restore-drill"

  # 先做一次新鲜备份：保证"备份时间点"与"当前数据"一致——
  # 否则备份之后产生的正常写入（新对话/新资料等）会让对照误报失败。
  echo "[drill] 先做一次新鲜备份 …"
  if ! bash "$ROOT/deploy/backup/backup.sh" >/dev/null; then
    echo "[drill] 备份失败，终止"; exit 1
  fi

  dump="$(latest db)"
  if [ -z "$dump" ]; then echo "[drill] 未找到数据库备份"; exit 1; fi
  if [ ! -d "$BK_DIR/storage-mirror" ]; then echo "[drill] 未找到原文件镜像"; exit 1; fi
  echo "[drill] 使用备份："
  echo "   db:    $dump"
  echo "   files: $BK_DIR/storage-mirror/"

  restore_db "$dump" "$target"
  rm -rf "$tmp"
  restore_files "$tmp"

  local fail=0
  echo "[drill] —— 数据库对照（原库 vs 恢复库）——"
  local t a b
  for t in users documents chunks conversations messages; do
    a=$(q "$LIVE_DB" "SELECT count(*) FROM $t")
    b=$(q "$target" "SELECT count(*) FROM $t")
    if [ "$a" = "$b" ]; then echo "   ✅ $t: $a 行"; else echo "   ❌ $t: $a vs $b"; fail=1; fi
  done

  echo "[drill] —— 内容指纹对照 ——"
  local lh rh
  lh=$(q "$LIVE_DB" "SELECT md5(coalesce(string_agg(id::text || role || left(content,200), '|' ORDER BY id), '')) FROM messages")
  rh=$(q "$target" "SELECT md5(coalesce(string_agg(id::text || role || left(content,200), '|' ORDER BY id), '')) FROM messages")
  if [ "$lh" = "$rh" ]; then echo "   ✅ 消息内容指纹一致（$lh）"; else echo "   ❌ 消息内容指纹不一致"; fail=1; fi

  echo "[drill] —— 原文件对照（全量 sha256 指纹）——"
  local lf rf
  lf=$(cd "$ROOT/server/data/storage" && find . -type f -exec sha256sum {} + | sort | sha256sum | cut -d' ' -f1)
  rf=$(cd "$tmp" && find . -type f -exec sha256sum {} + | sort | sha256sum | cut -d' ' -f1)
  if [ "$lf" = "$rf" ]; then echo "   ✅ 原文件指纹一致（$lf）"; else echo "   ❌ 原文件指纹不一致：$lf vs $rf"; fail=1; fi

  if [ "$fail" = 0 ]; then
    return 0
  fi
  return 1
}

# 演练入口：最多 3 轮——工具正在被使用（采集/对话持续写入）时，"备份快照 vs 实时库"
# 的对照会有正常竞态（演练期间新增的条目必然对不上）；任何一轮全量对照通过即判定通过，
# 连续 3 轮失败才报错（真实故障仍会被抓住：干净环境下第一轮就会全对）。
drill() {
  local attempt
  for attempt in 1 2 3; do
    echo "[drill] ════ 第 $attempt 轮 ════"
    if drill_once; then
      echo "[drill] ✅ 恢复演练通过（恢复库 secondbrain_restore 保留可查；原文件样例在 server/data/restore-drill）"
      return 0
    fi
    if [ "$attempt" -lt 3 ]; then
      echo "[drill] 本轮未通过对照（使用中的正常写入竞态）→ 5 秒后重试"
      sleep 5
    fi
  done
  echo "[drill] ❌ 恢复演练未通过（连续 3 轮）"
  exit 1
}

case "${1:-}" in
  drill) drill ;;
  db)    restore_db "${2:?用法: restore.sh db <dump.gpg> [目标库]}" "${3:-secondbrain_restore}" ;;
  files) restore_files "${2:-$ROOT/server/data/restore-drill}" ;;
  *)     echo "用法: restore.sh {drill | db <dump.gpg> [库名] | files [目录]}"; exit 1 ;;
esac
