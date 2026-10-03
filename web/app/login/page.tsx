"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";

export default function LoginPage() {
  const { t } = useLang();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username, password);
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("login.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <div className="card center-card">
        <h1 style={{ marginTop: 0 }}>second-brain</h1>
        <p className="muted">{t("login.hint")}</p>
        <form onSubmit={submit}>
          <label className="field">
            {t("login.username")}
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </label>
          <label className="field">
            {t("login.password")}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
            {busy ? t("login.submitting") : t("login.submit")}
          </button>
        </form>
      </div>
    </main>
  );
}
