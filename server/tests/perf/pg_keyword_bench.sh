#!/usr/bin/env bash
# T033 中文关键词检索压测（可复跑）：10 万条合成 chunks → trgm 索引 vs 全表扫描延时。
# 用法：bash server/tests/perf/pg_keyword_bench.sh
# 结果解读见 specs/001-core-qa/research.md R9。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PERF=secondbrain_perf
DC() { docker compose -f "$ROOT/deploy/docker-compose.yml" exec -T db "$@"; }

echo "[perf] 重建 $PERF（schema 取自实库）…"
DC psql -U secondbrain -d postgres -q -c "DROP DATABASE IF EXISTS $PERF;" -c "CREATE DATABASE $PERF;"
DC pg_dump -U secondbrain --schema-only secondbrain | DC psql -U secondbrain -q -d "$PERF"

echo "[perf] 灌 10 万条合成数据（约 640MB，1-2 分钟）…"
DC psql -U secondbrain -d "$PERF" -q -c "DROP INDEX IF EXISTS ix_chunks_content_trgm; DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;"
UID_=$(DC psql -U secondbrain -d secondbrain -tAc "SELECT id FROM users LIMIT 1;" | tr -d '\r')
DC psql -U secondbrain -d "$PERF" -q <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
INSERT INTO users (id, username, password_hash, created_at)
SELECT '$UID_', 'perf', 'x', now() WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = '$UID_');
INSERT INTO documents (id, owner_user_id, name, format, size_bytes, sha256, status, source_type, original_path, created_at, updated_at)
VALUES ('11111111-1111-1111-1111-111111111111', '$UID_', 'perf-doc', 'txt', 1, 'perf-sha', 'indexed', 'upload', 'perf', now(), now());
INSERT INTO chunks (id, owner_user_id, document_id, content, page, heading_path, embedding, created_at)
SELECT gen_random_uuid(), '$UID_', '11111111-1111-1111-1111-111111111111',
  CASE WHEN i % 100 = 0
       THEN '可观测性追踪系统 分布式链路分析 ' || repeat('追踪采样与指标聚合数据仓库 ', 28) || i
       ELSE '软件架构决策与工程实践要点 ' || repeat('scalable components and design patterns ', 18) || i END,
  (i % 1200) + 1, '性能抽测 / 模拟章节', array_fill(0.05::real, ARRAY[1024])::vector, now()
FROM generate_series(1, 100000) AS i;
CREATE INDEX ix_chunks_content_trgm ON chunks USING gin (content gin_trgm_ops);
ANALYZE chunks;
SQL

echo ""
echo "[perf] 体量："
DC psql -U secondbrain -d "$PERF" -tAc \
  "SELECT '  chunks '||count(*)||' 行 | trgm 索引 '||pg_size_pretty(pg_relation_size('ix_chunks_content_trgm'))||' | 表 '||pg_size_pretty(pg_total_relation_size('chunks')) FROM chunks;"

echo "[perf] 用例① ≥3 字中文模式（应走 trgm 索引）："
DC psql -U secondbrain -d "$PERF" -tAc \
  "EXPLAIN ANALYZE SELECT id FROM chunks WHERE content ILIKE '%可观测性追踪%' LIMIT 6;" \
  | grep -E "Scan|Execution" | sed 's/^/  /' || true

echo "[perf] 用例② 不存在词（≥3 字，索引仍生效）："
DC psql -U secondbrain -d "$PERF" -tAc \
  "EXPLAIN ANALYZE SELECT id FROM chunks WHERE content ILIKE '%量子纠缠校准框架%' LIMIT 6;" \
  | grep -E "Scan|Execution" | sed 's/^/  /' || true

echo "[perf] 用例③ 真·最差：2 字短词且不匹配（强制全表扫描）："
DC psql -U secondbrain -d "$PERF" -tAc \
  "EXPLAIN ANALYZE SELECT id FROM chunks WHERE content ILIKE '%宙斯%' OR content ILIKE '%赫拉%' LIMIT 6;" \
  | grep -E "Scan|Execution" | sed 's/^/  /' || true

echo ""
echo "[perf] 完成（判定：均需 < 2s，对照 spec NFR）"
