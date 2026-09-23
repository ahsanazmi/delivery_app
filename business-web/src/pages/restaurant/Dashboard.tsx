import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { getRestaurantDashboard, type RestaurantDashboard, type RestaurantOrderSummary } from "@/services/api/dashboardApi";
import { getRestaurantStatus, updateRestaurantStatus, type RestaurantStatus } from "@/services/api/statusApi";
import { rupees } from "@/utils/currency";

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function relativeTime(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function OrderRow({ order }: { order: RestaurantOrderSummary }) {
  return (
    <div className="order-row">
      <div className="order-row-main">
        <span className="order-number">{order.order_number}</span>
        <span className={`status-pill status-${order.status}`}>{statusLabel(order.status)}</span>
      </div>
      <div className="order-row-meta">
        <span>{order.customer_name}</span>
        <span>{order.item_count} item{order.item_count === 1 ? "" : "s"}</span>
        <span>{rupees(order.total)}</span>
        <span className="muted">{relativeTime(order.created_at)}</span>
      </div>
    </div>
  );
}

export default function RestaurantDashboardPage() {
  const { accessToken } = useSession();
  const [dashboard, setDashboard] = useState<RestaurantDashboard | null>(null);
  const [status, setStatus] = useState<RestaurantStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [togglingStatus, setTogglingStatus] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh = false) => {
      if (!accessToken) return;
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const [dashboardData, statusData] = await Promise.all([
          getRestaurantDashboard(accessToken),
          getRestaurantStatus(accessToken),
        ]);
        setDashboard(dashboardData);
        setStatus(statusData);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to load the dashboard.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [accessToken],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function handleToggleStatus() {
    if (!accessToken || !status) return;
    setTogglingStatus(true);
    setError(null);
    try {
      const updated = await updateRestaurantStatus(accessToken, !status.is_open);
      setStatus(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to update restaurant status.");
    } finally {
      setTogglingStatus(false);
    }
  }

  if (loading) {
    return <p className="page-center">Loading dashboard…</p>;
  }

  if (error && !dashboard) {
    return (
      <div className="error-banner" role="alert">
        {error}
        <button className="btn-secondary" style={{ marginLeft: 12 }} onClick={() => load()}>
          Try again
        </button>
      </div>
    );
  }

  if (!dashboard) return null;

  const isOpen = status?.is_open ?? dashboard.is_open;
  const isAccepting = status?.is_accepting_orders ?? dashboard.is_open;

  return (
    <div className="restaurant-dashboard">
      <div className="dashboard-toolbar">
        <div className={`status-card ${isOpen ? "status-open" : "status-closed"}`}>
          <div>
            <div className="status-name">{dashboard.restaurant_name}</div>
            <div className="status-badge">
              {isOpen ? "🟢 OPEN" : "🔴 CLOSED"}
            </div>
            {isOpen && !isAccepting && (
              <div className="status-note">Outside operating hours — not accepting orders right now.</div>
            )}
          </div>
          <button
            className={isOpen ? "btn-secondary" : "btn-primary"}
            style={{ width: "auto", padding: "0 18px" }}
            onClick={handleToggleStatus}
            disabled={togglingStatus}
          >
            {togglingStatus ? "Updating…" : isOpen ? "Close restaurant" : "Open restaurant"}
          </button>
        </div>
        <button className="btn-secondary" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <div className="stats-grid stats-grid-3">
        <div className="stat-card">
          <div className="label">Orders today</div>
          <div className="value">{dashboard.today_orders_count}</div>
          <div className="stat-breakdown">
            <span>{dashboard.pending_orders_count} pending</span>
            <span>{dashboard.preparing_orders_count} preparing</span>
            <span>{dashboard.ready_orders_count} ready</span>
            <span>{dashboard.completed_orders_count} completed</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Today's sales</div>
          <div className="value">{rupees(dashboard.today_sales)}</div>
          <div className="stat-breakdown">
            <span>From delivered orders today</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Pending earnings</div>
          <div className="value">{rupees(dashboard.pending_earnings)}</div>
          <div className="stat-breakdown">
            <span>From orders still in progress</span>
          </div>
        </div>
      </div>

      <h2 className="section-title">Pending orders</h2>
      {dashboard.pending_orders.length === 0 ? (
        <div className="empty-state">No pending orders — you're all caught up.</div>
      ) : (
        <div className="order-list">
          {dashboard.pending_orders.map((order) => (
            <OrderRow key={order.id} order={order} />
          ))}
        </div>
      )}

      <h2 className="section-title">Recent orders</h2>
      {dashboard.recent_orders.length === 0 ? (
        <div className="empty-state">No orders yet.</div>
      ) : (
        <div className="order-list">
          {dashboard.recent_orders.map((order) => (
            <OrderRow key={order.id} order={order} />
          ))}
        </div>
      )}
    </div>
  );
}
