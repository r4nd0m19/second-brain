"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { api, ApiError, Doc } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import ThemeToggle from "../_components/theme-toggle";
import LangToggle from "../_components/lang-toggle";

function SnapInner() {
  const { t, lang } = useLang();
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const from = params.get("from");
  const back =
    from === "chat"
      ? { href: "/chat/", label: t("snap.backToChat") }
      : from === "browser"
        ? { href: "/?source=browser", label: t("snap.backToBrowsing") }
        : { href: "/", label: t("snap.backToLibrary") };
  const [doc, setDoc] = useState<Doc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setError(t("snap.missingParam"));
      return;
    }
    api
      .getDoc(id)
      .then(setDoc)
      .catch((err) => setError(err instanceof ApiError ? err.message : t("snap.loadFailed")));
  }, [id, t]);

  return (
    <main className="container" style={{ maxWidth: 1200 }}>
      <div className="header">
        <div>
          <h1 style={{ fontSize: 20, marginBottom: 4 }}>{doc?.name ?? t("snap.title")}</h1>
          {doc && (
            <div className="muted">
              {doc.site_name}
              {doc.last_captured_at
                ? t("snap.visitedAt", {
                    time: new Date(doc.last_captured_at).toLocaleString(
                      lang === "zh" ? "zh-CN" : "en-US",
                    ),
                  })
                : ""}
              {doc.source_url && (
                <>
                  {" · "}
                  <a href={doc.source_url} target="_blank" rel="noreferrer">
                    {t("snap.openOriginal")}
                  </a>
                </>
              )}
            </div>
          )}
        </div>
        <div className="hdr-actions">
          <Link className="btn" href={back.href}>
            {back.label}
          </Link>
          <ThemeToggle />
          <LangToggle />
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {doc && (
        <div className="card snap-scroll" style={{ padding: 0, overflowX: "auto" }}>
          {/* 空 sandbox：禁脚本 / 表单 / 弹窗 / 顶层跳转（快照按不可信内容处理；R4）
              手机端：iframe 保持桌面宽（CSS min-width），外层横向滚动——不裁切、不改原排版 */}
          <iframe
            sandbox=""
            src={`/api/documents/${doc.id}/snapshot`}
            style={{ width: "100%", height: "78vh", border: "0", background: "#fff", display: "block" }}
            title={t("snap.title")}
          />
        </div>
      )}
    </main>
  );
}

export default function SnapPage() {
  const { t } = useLang();
  return (
    <Suspense
      fallback={
        <main className="container">
          <p className="muted">{t("snap.loading")}</p>
        </main>
      }
    >
      <SnapInner />
    </Suspense>
  );
}
