import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { getUnreadRestaurantNotificationCount } from "@/services/api/notificationsApi";
import { getMyRestaurantProfile, type RestaurantSummary } from "@/services/api/restaurantApi";

// Same 15s cadence the notifications page itself polls at — a nav badge
// lagging the page's own count by up to one interval is an acceptable
// tradeoff against adding a second, faster poll loop just for the badge.
const POLL_INTERVAL_MS = 15000;

export function RestaurantLayout() {
  const navigate = useNavigate();
  const { user, signOut, accessToken } = useSession();
  const [unreadCount, setUnreadCount] = useState(0);
  const [restaurant, setRestaurant] = useState<RestaurantSummary | null>(null);

  const loadUnreadCount = useCallback(async () => {
    if (!accessToken) return;
    try {
      const { unread_count } = await getUnreadRestaurantNotificationCount(accessToken);
      setUnreadCount(unread_count);
    } catch {
      // Silent — a stale/missing badge count must never block the portal.
    }
  }, [accessToken]);

  useEffect(() => {
    void loadUnreadCount();
    const interval = setInterval(() => {
      void loadUnreadCount();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadUnreadCount]);

  // Loaded once per session so a restaurant still under review (or
  // rejected/suspended) says so on every page, not just the dashboard.
  useEffect(() => {
    if (!accessToken) return;
    getMyRestaurantProfile(accessToken)
      .then(({ restaurants }) => setRestaurant(restaurants[0] ?? null))
      .catch(() => {
        // Silent — same as the badge: a missing banner must never block the portal.
      });
  }, [accessToken]);

  async function handleLogout() {
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1>Restaurant portal</h1>
          {user && <p className="subtitle" style={{ margin: "4px 0 0" }}>{user.name}</p>}
        </div>
        <button className="btn-secondary" onClick={handleLogout}>
          Logout
        </button>
      </div>
      <nav className="portal-nav">
        <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Dashboard
        </NavLink>
        <NavLink to="/profile" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Restaurant Profile
        </NavLink>
        <NavLink to="/hours" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Operating Hours
        </NavLink>
        <NavLink to="/categories" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Categories
        </NavLink>
        <NavLink to="/products" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Products
        </NavLink>
        <NavLink to="/orders" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Orders
        </NavLink>
        <NavLink to="/notifications" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Notifications
          {unreadCount > 0 && <span className="new-order-badge">{unreadCount}</span>}
        </NavLink>
      </nav>
      {restaurant?.approval_status === "PENDING" && (
        <div className="approval-banner" role="status">
          <strong>Your application is under review.</strong> Set up your menu, categories and hours now. Customers will
          see {restaurant.name} as soon as our team approves it.
        </div>
      )}
      {restaurant?.approval_status === "REJECTED" && (
        <div className="approval-banner approval-rejected" role="alert">
          <strong>Your application was not approved.</strong>
          {restaurant.rejection_reason ? ` Reason: ${restaurant.rejection_reason}` : ""} Please contact Say Hi Chai
          support to reapply.
        </div>
      )}
      {restaurant?.approval_status === "SUSPENDED" && (
        <div className="approval-banner approval-suspended" role="alert">
          <strong>{restaurant.name} is suspended</strong> and hidden from customers. Please contact Say Hi Chai support.
        </div>
      )}
      <Outlet />
    </div>
  );
}
