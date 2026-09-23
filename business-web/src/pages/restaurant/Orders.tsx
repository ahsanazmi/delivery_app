import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { listRestaurantOrders, type OrderListItem, type StatusFilter } from "@/services/api/ordersApi";
import { rupees } from "@/utils/currency";

const FILTERS: { value: StatusFilter | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "confirmed", label: "Confirmed" },
  { value: "preparing", label: "Preparing" },
  { value: "ready", label: "Ready" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

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

// Frontend State Synchronization (Phase 19) — this is the one screen where
// staleness matters most: a new order the owner hasn't seen yet is a
// missed/delayed pickup. Plain interval polling (no WebSocket, no
// TanStack Query — neither exists in this app yet) matches this phase's
// own "polling is acceptable for MVP validation" guidance.
const POLL_INTERVAL_MS = 15000;

export default function OrdersPage() {
  const { accessToken } = useSession();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<StatusFilter | "all">("all");
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh = false) => {
      if (!accessToken) return;
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await listRestaurantOrders(accessToken, filter === "all" ? undefined : filter);
        setOrders(data);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to load orders.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [accessToken, filter],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const interval = setInterval(() => {
      void load(true);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load]);

  const pendingCount = orders.filter((o) => o.status === "placed").length;

  return (
    <div className="orders-page">
      <div className="dashboard-toolbar">
        <h2 className="section-title" style={{ margin: 0 }}>
          Incoming orders
          {pendingCount > 0 && <span className="new-order-badge">{pendingCount} NEW</span>}
        </h2>
        <button className="btn-secondary" onClick={() => load(true)} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="portal-nav" style={{ marginBottom: 20 }}>
        {FILTERS.map((f) => (
          <button
            key={f.value}
            className={filter === f.value ? "portal-nav-link active" : "portal-nav-link"}
            style={{ background: "none", border: "none", cursor: "pointer" }}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <p className="page-center">Loading orders…</p>
      ) : orders.length === 0 ? (
        <div className="empty-state">No orders in this view.</div>
      ) : (
        <div className="order-list">
          {orders.map((order) => (
            <div
              key={order.id}
              className="order-row order-row-clickable"
              onClick={() => navigate(`/orders/${order.id}`)}
            >
              <div className="order-row-main">
                <span className="order-number">
                  {order.status === "placed" && <span className="new-order-dot" />}
                  New Order #{order.order_number}
                </span>
                <span className={`status-pill status-${order.status}`}>{statusLabel(order.status)}</span>
              </div>
              <div className="order-row-meta">
                <span>Customer: {order.customer_name_masked}</span>
                <span>Items: {order.item_count}</span>
                <span>Total: {rupees(order.total)}</span>
                <span>Net: {rupees(order.net_amount)}</span>
                <span>Payment: {order.payment_method.toUpperCase()} · {statusLabel(order.payment_status)}</span>
                <span className="muted">{relativeTime(order.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
