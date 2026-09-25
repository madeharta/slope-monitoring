import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      const dest = location.state?.from?.pathname || "/";
      navigate(dest, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-brand">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 20 L8.5 7 L12.5 14 L15.5 9 L22 20 Z" /></svg>
        <b>MAGRIS</b><span>LEWS</span>
      </div>
      <form onSubmit={handleSubmit} className="login-card">
        <h1>Masuk</h1>
        <p className="login-sub">Slope &amp; Blast Monitoring Console</p>
        <label className="login-field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="username"
            placeholder="operator@namadomain.id"
          />
        </label>
        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            placeholder="••••••••"
          />
        </label>
        {error && <div className="login-error" role="alert">{error}</div>}
        <button type="submit" className="login-submit" disabled={submitting}>
          {submitting ? "Masuk…" : "Masuk"}
        </button>
      </form>
    </div>
  );
}
