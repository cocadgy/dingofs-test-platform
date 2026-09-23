import { useEffect, useState } from "react";
import { api } from "../../api/client";
export function ProfilePage({
  email,
  onEmailSaved,
  onPasswordChanged,
  onDirty,
}: {
  email: string | null;
  onEmailSaved: (email: string) => void;
  onPasswordChanged: () => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [address, setAddress] = useState(email || "");
  const [emailPassword, setEmailPassword] = useState("");
  const [password, setPassword] = useState("");
  const [next, setNext] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty =
    address !== (email || "") ||
    !!emailPassword ||
    !!password ||
    !!next ||
    !!confirmPassword;
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  async function save(e: React.FormEvent, mode: "email" | "password") {
    e.preventDefault();
    setError("");
    setNotice("");
    if (mode === "password" && next !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    setBusy(true);
    try {
      const result = await api<{ email: string; reauthenticate: boolean }>(
        "/auth/profile",
        "PATCH",
        mode === "email"
          ? { email: address, current_password: emailPassword }
          : { new_password: next, current_password: password },
      );
      if (mode === "email") {
        onEmailSaved(result.email);
        setEmailPassword("");
        setNotice("邮箱已更新");
      } else {
        setPassword("");
        setNext("");
        setConfirmPassword("");
        setNotice("密码已修改，请重新登录");
        onPasswordChanged();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">PLATFORM / ACCOUNT</p>
          <h1>个人设置</h1>
          <p className="muted">每次修改邮箱或密码，都需要验证当前登录密码。</p>
        </div>
      </header>
      {!email && <p className="error">此账号尚未填写邮箱，请补充有效邮箱。</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
      <div className="profile-grid">
        <form className="panel detail" onSubmit={(e) => save(e, "email")}>
          <h2>邮箱</h2>
          <div className="form-grid">
            <label>
              邮箱
              <input
                type="email"
                required
                maxLength={254}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
            <label>
              当前密码
              <input
                aria-label="修改邮箱的当前密码"
                type="password"
                autoComplete="current-password"
                required
                maxLength={1024}
                value={emailPassword}
                onChange={(e) => setEmailPassword(e.target.value)}
              />
            </label>
          </div>
          <div className="actions">
            <button className="primary" disabled={busy}>
              修改邮箱
            </button>
          </div>
        </form>
        <form className="panel detail" onSubmit={(e) => save(e, "password")}>
          <h2>密码</h2>
          <p className="muted">
            新密码至少 6 位；修改后所有已登录会话失效，需要重新登录。
          </p>
          <div className="form-grid">
            <label>
              当前密码
              <input
                aria-label="修改密码的当前密码"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                maxLength={1024}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              新密码
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={6}
                maxLength={1024}
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            </label>
            <label>
              确认新密码
              <input
                type="password"
                autoComplete="new-password"
                required
                minLength={6}
                maxLength={1024}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </label>
          </div>
          <div className="actions">
            <button className="primary" disabled={busy}>
              修改密码
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
