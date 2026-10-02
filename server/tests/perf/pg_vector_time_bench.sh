#!/usr/bin/env bash
# T044 时间过滤向量检索压测（可复跑）：10 万 chunks + 24 个网页文档（浏览时间分散 120 天，
# 7 天窗口选择性 ≈ 8%）。对比：迭代扫描 off vs relaxed_order（R5 生产写法）vs 无过滤基线。
# 用法：bash server/tests/perf/pg_vector_time_bench.sh ；结果记录见 specs/002-browser-capture/research.md R5。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PERF=secondbrain_perf_vec
DC() { docker compose -f "$ROOT/deploy/docker-compose.yml" exec -T db "$@"; }

if [[ "${REUSE:-0}" != "1" ]]; then
echo "[perf] 重建 $PERF（schema 取自实库）…"
DC psql -U secondbrain -d postgres -q -c "DROP DATABASE IF EXISTS $PERF;" -c "CREATE DATABASE $PERF;"
DC pg_dump -U secondbrain --schema-only secondbrain | DC psql -U secondbrain -q -d "$PERF"
DC psql -U secondbrain -d "$PERF" -q -c "DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;"

UID_=$(DC psql -U secondbrain -d secondbrain -tAc "SELECT id FROM users LIMIT 1;" | tr -d '\r')
echo "[perf] 灌 10 万条合成 chunks（1024 维随机向量；约 1–3 分钟）…"
DC psql -U secondbrain -d "$PERF" -q -v ON_ERROR_STOP=1 <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
INSERT INTO users (id, username, password_hash, created_at)
  SELECT '$UID_', 'perf', 'x', now() WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = '$UID_');
INSERT INTO documents (id, owner_user_id, name, format, size_bytes, sha256, status, source_type, original_path,
                       source_url, site_name, first_captured_at, last_captured_at, visit_count, created_at, updated_at)
SELECT ('22222222-2222-2222-2222-' || lpad(i::text, 12, '0'))::uuid,
       '$UID_', 'perf-page-' || i, 'html', 1, 'perf-sha-' || i, 'indexed', 'browser',
       'perf', 'https://perf.example/p' || i, 'perf.example',
       now() - (i * interval '5 days'), now() - (i * interval '5 days'), 1, now(), now()
FROM generate_series(0, 23) AS i;
INSERT INTO chunks (id, owner_user_id, document_id, content, page, heading_path, embedding, created_at)
SELECT gen_random_uuid(), '$UID_',
       ('22222222-2222-2222-2222-' || lpad((i % 24)::text, 12, '0'))::uuid,
       'perf chunk ' || i, NULL, NULL,
       array_fill(random()::real, ARRAY[1024])::vector, now()
FROM generate_series(1, 100000) AS i;
SET max_parallel_maintenance_workers = 0;  -- 容器 /dev/shm 受限：索引构建走后端私有内存
SET maintenance_work_mem = '512MB';
CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
ANALYZE chunks;
ANALYZE documents;
SQL
else
  echo "[perf] REUSE=1：复用既有 $PERF 数据集"
fi

UID_=$(DC psql -U secondbrain -d secondbrain -tAc "SELECT id FROM users LIMIT 1;" | tr -d '\r')
# 查询向量用字面量（贴近应用的绑定参数形态；子查询常量会让 planner 误判）
VEC=$(DC psql -U secondbrain -d "$PERF" -tAc "SELECT embedding FROM chunks LIMIT 1" | tr -d '\r')
if [[ -z "$VEC" ]]; then echo "[perf] 数据集为空，请先整跑一次（不带 REUSE=1）"; exit 1; fi

echo ""
echo "[perf] 体量："
DC psql -U secondbrain -d "$PERF" -tAc \
  "SELECT '  chunks ' || count(*) || ' 行 | hnsw ' || pg_size_pretty(pg_relation_size('ix_chunks_embedding_hnsw')) FROM chunks;"

Q="SELECT c.id FROM chunks c JOIN documents d ON c.document_id = d.id \
WHERE c.owner_user_id = '$UID_' \
AND d.last_captured_at >= now() - interval '7 days' AND d.last_captured_at < now() \
ORDER BY c.embedding <=> '$VEC'::vector LIMIT 6;"
Q_ALL="SELECT c.id FROM chunks c JOIN documents d ON c.document_id = d.id \
WHERE c.owner_user_id = '$UID_' \
ORDER BY c.embedding <=> '$VEC'::vector LIMIT 6;"

echo "[perf] 用例① 时间过滤 + 迭代扫描 OFF（默认 ef_search=40；预期 overfiltering 或回退精确扫描）："
DC psql -U secondbrain -d "$PERF" -tAc "SET hnsw.iterative_scan = off; EXPLAIN ANALYZE $Q" \
  | grep -E "Scan|Sort Method|Execution Time|Rows Removed" | sed 's/^/  /'

echo "[perf] 用例② 时间过滤 + relaxed_order + ef_search=100（R5 生产写法）："
DC psql -U secondbrain -d "$PERF" -tAc "SET hnsw.iterative_scan = relaxed_order; SET hnsw.ef_search = 100; EXPLAIN ANALYZE $Q" \
  | grep -E "Scan|Sort Method|Execution Time|Rows Removed" | sed 's/^/  /'

echo "[perf] 用例③ 无时间过滤基线（ef_search=100）："
DC psql -U secondbrain -d "$PERF" -tAc "SET hnsw.ef_search = 100; EXPLAIN ANALYZE $Q_ALL" \
  | grep -E "Scan|Sort Method|Execution Time|Rows Removed" | sed 's/^/  /'

echo ""
echo "[perf] 完成（判定：时间过滤查询不显著劣于无过滤基线，且全部 < 1s）"
