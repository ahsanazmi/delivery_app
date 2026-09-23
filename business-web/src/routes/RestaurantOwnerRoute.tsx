import { Navigate, Outlet } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";

/**
 * Gates every restaurant-owner page behind session status AND role — a
 * customer or rider who somehow ends up with a valid session here sees a
 * clear "not authorized" screen rather than a confusing redirect loop or,
 * worse, a half-rendered dashboard. This is UX only: the real security
 * boundary is the backend (require_roles(RESTAURANT_OWNER) on every
 * /api/v1/restaurant/* and /api/v1/restaurants/* mutation), so a client-side
 * bypass here can't expose any other owner's data.
 */
export function RestaurantOwnerRoute() {
  const { status, user, signOut } = useSession();

  if (status === "loading") {
    return <div className="page-center">Loading…</div>;
  }

  if (status === "anonymous") {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== "RESTAURANT_OWNER") {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="brand-mark">🚫</div>
          <h1>Not authorized</h1>
          <p className="subtitle">
            This portal is for restaurant owners only. Your account ({user?.role.toLowerCase()}) doesn't have
            access here.
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
