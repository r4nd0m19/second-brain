import React from "react";

/** 搜索命中词高亮（不区分大小写，仅首个命中）。 */
export function highlight(text: string, q: string): React.ReactNode {
  const needle = q.trim().toLowerCase();
  if (!needle) return text;
  const idx = text.toLowerCase().indexOf(needle);
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark>{text.slice(idx, idx + needle.length)}</mark>
      {text.slice(idx + needle.length)}
    </>
  );
}
