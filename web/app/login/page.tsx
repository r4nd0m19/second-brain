"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
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
      setError(err instanceof ApiError ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <div className="card center-card">
        <h1 style={{ marginTop: 0 }}>second-brain</h1>
        <p className="muted">登录你的第二大脑</p>
        <form onSubmit={submit}>
          <label className="field">
            用户名
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </label>
          <label className="field">
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
            {busy ? "登录中…" : "登录"}
          </button>
        </form>
      </div>
    </main>
  );
}
