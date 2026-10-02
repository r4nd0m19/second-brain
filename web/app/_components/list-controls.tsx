"use client";

export type SortOption = {
  value: string;
  label: string;
  /** 切换到该字段时的默认方向 */
  dir: "asc" | "desc";
};

/** 列表工具条：搜索（防抖在上层）+ 排序字段/方向 + 结果计数 */
export function ListToolbar({
  q,
  onQChange,
  sort,
  sortOptions,
  onSortChange,
  total,
  loading,
}: {
  q: string;
  onQChange: (v: string) => void;
  /** 形如 "-created_at"（前缀 - 表示倒序） */
  sort: string;
  sortOptions: SortOption[];
  onSortChange: (v: string) => void;
  total: number;
  loading: boolean;
}) {
  const desc = sort.startsWith("-");
  const field = desc ? sort.slice(1) : sort;
  return (
    <div className="list-toolbar">
      <input
        className="list-search"
        type="search"
        placeholder="搜索标题 / 站点 / 正文…"
        value={q}
        onChange={(e) => onQChange(e.target.value)}
      />
      <select
        className="list-sort"
        value={field}
        onChange={(e) => {
          const opt = sortOptions.find((o) => o.value === e.target.value);
          if (opt) onSortChange((opt.dir === "asc" ? "" : "-") + opt.value);
        }}
      >
        {sortOptions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <button
        className="btn list-dir"
        title={desc ? "当前：降序（点击切升序）" : "当前：升序（点击切降序）"}
        aria-label={desc ? "切换为升序" : "切换为降序"}
        onClick={() => onSortChange((desc ? "" : "-") + field)}
      >
        {desc ? "↓" : "↑"}
      </button>
      <span className="muted list-count">{loading ? "更新中…" : `共 ${total} 条`}</span>
    </div>
  );
}

function pageNumbers(page: number, totalPages: number): (number | "…")[] {
  const wanted = new Set<number>([1, totalPages, page]);
  for (const candidate of [page - 1, page + 1]) {
    if (candidate >= 1 && candidate <= totalPages) wanted.add(candidate);
  }
  const sorted = [...wanted].sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  let prev = 0;
  for (const n of sorted) {
    if (prev && n - prev > 1) out.push("…");
    out.push(n);
    prev = n;
  }
  return out;
}

/** 页码分页条（首页/末页/当前页±1 + 省略号；单页时隐藏） */
export function Pager({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className="pager">
      <button className="btn pager-btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ‹ 上一页
      </button>
      {pageNumbers(page, totalPages).map((n, i) =>
        n === "…" ? (
          <span key={`gap-${i}`} className="pager-ellipsis">
            …
          </span>
        ) : (
          <button
            key={n}
            className={`btn pager-btn${n === page ? " pager-current" : ""}`}
            aria-current={n === page ? "page" : undefined}
            onClick={() => onPage(n)}
          >
            {n}
          </button>
        ),
      )}
      <button
        className="btn pager-btn"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
      >
        下一页 ›
      </button>
      <span className="muted pager-info">
        第 {page}/{totalPages} 页
      </span>
    </div>
  );
}
