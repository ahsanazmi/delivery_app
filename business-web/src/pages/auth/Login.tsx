import { FormEvent, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";

export default function Login() {
  const navigate = useNavigate();
  const { signIn, signOut, status } = useSession();
  const [email, setEmail] = useState("owner@demo.com");
  const [password, setPassword] = useState("Demo@1234");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (status === "authenticated") {
    return <Navigate to="/dashboard" replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const user = await signIn(email.trim(), password);
      if (user.role !== "RESTAURANT_OWNER") {
        await signOut();
        setError("This account is not authorized for the restaurant portal.");
        return;
      }
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to log in.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand-mark">🍽️</div>
        <h1>Restaurant portal</h1>
        <p className="subtitle">Manage your restaurant profile and menu.</p>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <div className="error-banner" role="alert">{error}</div>}
          <button className="btn-primary" type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
