import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  listRestaurantNotifications,
  markAllRestaurantNotificationsRead,
  markRestaurantNotificationRead,
  type Notification,
} from "@/services/api/notificationsApi";

const TYPE_ICON: Record<string, string> = {
  restaurant_new_order: "🧾",
  restaurant_order_cancelled: "❌",
  rider_assigned: "🛵",
  payment_update: "💳",
  delivery_updated: "⚠️",
  order_delivered: "📦",
  system: "🔔",
};

function relativeTime(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

// Same polling cadence Orders.tsx already established for this app (no
// WebSocket, no TanStack Query in this app yet) — consistent with every
// other screen here, not a new pattern introduced just for this one.
const POLL_INTERVAL_MS = 15000;

export default function NotificationsPage() {
  const { accessToken } = useSession();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(
    async (isRefresh = false) => {
      if (!accessToken) return;
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const data = await listRestaurantNotifications(accessToken);
        setNotifications(data);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to load notifications.");
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

  useEffect(() => {
    const interval = setInterval(() => {
      void load(true);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load]);

  async function handleOpen(notification: Notification) {
    if (!accessToken) return;
    if (!notification.is_read) {
      setNotifications((current) =>
        current.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n)),
      );
      markRestaurantNotificationRead(accessToken, notification.id).catch(() => undefined);
    }
    if (notification.order_id) {
      navigate(`/orders/${notification.order_id}`);
    }
  }

  async function handleMarkAllRead() {
    if (!accessToken) return;
    setMarkingAll(true);
    setNotifications((current) => current.map((n) => ({ ...n, is_read: true })));
    try {
      await markAllRestaurantNotificationsRead(accessToken);
    } catch {
      void load();
    } finally {
      setMarkingAll(false);
    }
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  return (
    <div className="notifications-page">
      <div className="dashboard-toolbar">
        <h2 className="section-title" style={{ margin: 0 }}>
          Notifications
          {unreadCount > 0 && <span className="new-order-badge">{unreadCount} UNREAD</span>}
        </h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-secondary" onClick={handleMarkAllRead} disabled={markingAll || unreadCount === 0}>
            {markingAll ? "Marking…" : "Mark all read"}
          </button>
          <button className="btn-secondary" onClick={() => load(true)} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <p className="page-center">Loading notifications…</p>
      ) : notifications.length === 0 ? (
        <div className="empty-state">No notifications yet.</div>
      ) : (
        <div className="order-list">
          {notifications.map((notification) => (
            <div
              key={notification.id}
              className={
                notification.order_id ? "order-row order-row-clickable" : "order-row"
              }
              onClick={() => handleOpen(notification)}
            >
              <div className="order-row-main">
                <span className="order-number">
                  {!notification.is_read && <span className="new-order-dot" />}
                  {TYPE_ICON[notification.type] ?? "🔔"} {notification.title}
                </span>
              </div>
              <div className="order-row-meta">
                <span>{notification.body}</span>
                <span className="muted">{relativeTime(notification.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
