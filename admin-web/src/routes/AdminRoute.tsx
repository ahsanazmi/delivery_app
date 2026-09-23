import { Navigate, Outlet } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";

/**
 * Gates every admin page behind session status AND role — a customer,
 * rider, or restaurant owner who somehow ends up with a valid session here
 * sees a clear "not authorized" screen rather than a confusing redirect
 * loop or a half-rendered dashboard. This is UX only: the real security
 * boundary is the backend (require_admin on every /api/v1/admin/* route —
 * see backend/app/api/v1/deps.py), so a client-side bypass here can't
 * expose any admin-only data or action.
 */
export function AdminRoute() {
  const { status, user, signOut } = useSession();

  if (status === "loading") {
    return <div className="page-center">Loading…</div>;
  }

  if (status === "anonymous") {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== "ADMIN") {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="brand-mark">🚫</div>
          <h1>Not authorized</h1>
          <p className="subtitle">
            This portal is for administrators only. Your account ({user?.role.toLowerCase()}) doesn't have access
            here.
          </p>
          <button className="btn-secondary" onClick={() => signOut()}>
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return <Outlet />;
}
