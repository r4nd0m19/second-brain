"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { api, ApiError, Doc } from "@/lib/api";

function SnapInner() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const fromChat = params.get("from") === "chat";
  const [doc, setDoc] = useState<Doc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setError("缺少条目参数");
      return;
    }
    api
      .getDoc(id)
      .then(setDoc)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }, [id]);

  return (
    <main className="container" style={{ maxWidth: 1200 }}>
      <div className="header">
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>{doc?.name ?? "页面快照"}</h1>
          {doc && (
            <div className="muted">
              {doc.site_name}
              {doc.last_captured_at
                ? ` · 浏览于 ${new Date(doc.last_captured_at).toLocaleString("zh-CN")}`
                : ""}
              {doc.source_url && (
                <>
                  {" · "}
                  <a href={doc.source_url} target="_blank" rel="noreferrer">
                    打开原文 ↗
                  </a>
                </>
              )}
            </div>
          )}
        </div>
        <div>
          <Link
            className="btn"
            style={{ marginRight: 8, textDecoration: "none" }}
            href={fromChat ? "/chat/" : "/"}
          >
            {fromChat ? "返回对话" : "返回资料库"}
          </Link>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {doc && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {/* 空 sandbox：禁脚本 / 表单 / 弹窗 / 顶层跳转（快照按不可信内容处理；R4） */}
          <iframe
            sandbox=""
            src={`/api/documents/${doc.id}/snapshot`}
            style={{ width: "100%", height: "78vh", border: "0", background: "#fff", display: "block" }}
            title="页面快照"
          />
        </div>
      )}
    </main>
  );
}

export default function SnapPage() {
  return (
    <Suspense
      fallback={
        <main className="container">
          <p className="muted">加载中…</p>
        </main>
      }
    >
      <SnapInner />
    </Suspense>
  );
}
