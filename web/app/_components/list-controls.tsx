"use client";

import { useState } from "react";

import { useLang } from "@/lib/i18n";

export type SortOption = {
  value: string;
  label: string;
  /** 切换到该字段时的默认方向 */
  dir: "asc" | "desc";
};

/** 列表工具条：搜索（防抖在上层）+ 排序字段/方向 + 结果计数。
 *  手机端（≤720px）：排序控件收进底部弹层（范式：筛选面板=bottom sheet，选中即生效、底部「完成」关闭）。 */
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
  const { t } = useLang();
  const [sheetOpen, setSheetOpen] = useState(false);
  const desc = sort.startsWith("-");
  const field = desc ? sort.slice(1) : sort;
  return (
    <>
      <div className="list-toolbar">
        <input
          className="list-search"
          type="search"
          placeholder={t("list.searchPlaceholder")}
          value={q}
          onChange={(e) => onQChange(e.target.value)}
        />
        {/* 桌面排序控件（手机隐藏，见 globals.css） */}
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
          title={desc ? t("list.sortDescTitle") : t("list.sortAscTitle")}
          aria-label={desc ? t("list.toAsc") : t("list.toDesc")}
          onClick={() => onSortChange((desc ? "" : "-") + field)}
        >
          {desc ? "↓" : "↑"}
        </button>
        {/* 手机：打开筛选弹层（桌面隐藏） */}
        <button
          className="btn list-filter-btn"
          aria-expanded={sheetOpen}
          onClick={() => setSheetOpen(true)}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 7.5h16M4 16.5h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <circle cx="9" cy="7.5" r="2.2" fill="var(--panel)" stroke="currentColor" strokeWidth="1.8" />
            <circle cx="15" cy="16.5" r="2.2" fill="var(--panel)" stroke="currentColor" strokeWidth="1.8" />
          </svg>
          {t("list.filter")}
        </button>
        <span className="muted list-count">
          {loading ? t("list.updating") : t("list.count", { total })}
        </span>
      </div>

      {/* 筛选底部弹层（手机专用；桌面 display:none）。选中即生效（列表在弹层后即时刷新），「完成」关闭 */}
      {sheetOpen && <div className="sheet-scrim" onClick={() => setSheetOpen(false)} />}
      <div
        className={`sheet${sheetOpen ? " sheet-open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={t("list.filterTitle")}
      >
        <div className="sheet-handle" />
        <div className="sheet-head">
          <span className="sheet-title">{t("list.filterTitle")}</span>
          <button className="btn sheet-close" aria-label={t("list.done")} onClick={() => setSheetOpen(false)}>
            ✕
          </button>
        </div>
        <div className="sheet-body">
          <div className="sheet-section-title">{t("list.sortSection")}</div>
          {sortOptions.map((o) => (
            <button
              key={o.value}
              className={`sheet-option${o.value === field ? " active" : ""}`}
              onClick={() =>
                onSortChange(
                  // 重选当前字段：保持方向；换字段：用该字段默认方向
                  o.value === field ? sort : (o.dir === "asc" ? "" : "-") + o.value,
                )
              }
            >
              <span>{o.label}</span>
              <span className="sheet-option-dir">{o.value === field ? (desc ? "↓" : "↑") : ""}</span>
            </button>
          ))}
          <div className="sheet-section-title">{t("list.dirSection")}</div>
          <div className="sheet-dir-row">
            <button
              className={`sheet-chip${!desc ? " active" : ""}`}
              onClick={() => onSortChange(field)}
            >
              ↑ {t("list.asc")}
            </button>
            <button
              className={`sheet-chip${desc ? " active" : ""}`}
              onClick={() => onSortChange("-" + field)}
            >
              ↓ {t("list.desc")}
            </button>
          </div>
        </div>
        <div className="sheet-foot">
          <button className="btn btn-primary sheet-done" onClick={() => setSheetOpen(false)}>
            {t("list.done")}
          </button>
        </div>
      </div>
    </>
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
  const { t } = useLang();
  if (totalPages <= 1) return null;
  return (
    <div className="pager">
      <button className="btn pager-btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t("list.prev")}
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
        {t("list.next")}
      </button>
      <span className="muted pager-info">
        {t("list.pageOf", { page, totalPages })}
      </span>
    </div>
  );
}
