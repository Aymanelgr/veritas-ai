import { useState } from "react";
import { errorMessage, login } from "../api.js";
import { Logo } from "../icons.jsx";

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login(email, password));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card panel" onSubmit={submit}>
        <div className="brand-login"><Logo size={44} /><div><h1>Veritas AI</h1><p className="muted">Sign in to review documents</p></div></div>
        <label>
          <span>Email</span>
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </label>
        <label>
          <span>Password</span>
          <input type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted small">No account? Ask your administrator. The first admin is created with
          <code> python -m backend.manage create-user --role admin</code>.</p>
      </form>
    </div>
  );
}
