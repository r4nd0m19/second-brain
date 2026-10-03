"use client";

/**
 * 日期选择（2026-10-03）：原生 <input type="date"> 的显示格式由浏览器语言决定、
 * 页面无法控制（Chrome 官方 FAQ）——改用业界组件 react-day-picker + 自绘触发钮/弹层，
 * 日历与格式跟随界面语言（zh/en）；value 契约不变，仍为 "YYYY-MM-DD"（与后端参数一致）。
 */

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import "react-day-picker/style.css";

import { useLang } from "@/lib/i18n";

// 日历与中文 locale 数据按需加载：仅首次打开弹层时下载（该控件使用频率低，不进页面首包）
const Calendar = dynamic(
  async () => {
    const [{ DayPicker }, { zhCN }] = await Promise.all([
      import("react-day-picker"),
      import("react-day-picker/locale/zh-CN"),
    ]);
    return function Calendar(props: ComponentProps<typeof DayPicker>) {
      const { lang } = useLang();
      return <DayPicker {...props} locale={lang === "zh" ? zhCN : undefined} />;
    };
  },
  { ssr: false },
);

/** "YYYY-MM-DD" → 本地 Date（不经 new Date(str)，避免按 UTC 解释的时区偏移）。 */
function parseISO(v: string): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!m) return undefined;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function toISO(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export default function DateField({
  value,
  onChange,
}: {
  /** "YYYY-MM-DD" 或 ""（未选） */
  value: string;
  onChange: (v: string) => void;
}) {
  const { t, lang } = useLang();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // 弹层交互：点击外部 / Escape 关闭
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = parseISO(value);
  const display = selected
    ? selected.toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      })
    : t("date.pick");

  return (
    <div className="date-field" ref={rootRef}>
      <button
        type="button"
        className={`btn date-field-btn${value ? "" : " date-field-empty"}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {display}
      </button>
      {open && (
        <div className="date-pop" role="dialog" aria-label={t("date.pick")}>
          <Calendar
            mode="single"
            selected={selected}
            defaultMonth={selected}
            onSelect={(d) => {
              onChange(d ? toISO(d) : "");
              setOpen(false);
            }}
          />
          {value && (
            <div className="date-pop-foot">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  onChange("");
                  setOpen(false);
                }}
              >
                {t("date.clear")}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
