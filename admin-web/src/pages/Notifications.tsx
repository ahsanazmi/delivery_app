import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminNotifications,
  markAdminNotificationRead,
  markAllAdminNotificationsRead,
  type AdminNotification,
} from "@/services/api/adminApi";

function formatType(type: string): string {
  return type
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function Notifications() {
  const { accessToken } = useSession();
  const [notifications, setNotifications] = useState<AdminNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setNotifications(await getAdminNotifications(accessToken));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load notifications.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleMarkRead(notification: AdminNotification) {
    if (!accessToken || notification.is_read) return;
    setActioningId(notification.id);
    setError(null);
    try {
      const updated = await markAdminNotificationRead(accessToken, notification.id);
      setNotifications((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to mark notification as read.");
    } finally {
      setActioningId(null);
    }
  }

  async function handleMarkAllRead() {
    if (!accessToken) return;
    setMarkingAll(true);
    setError(null);
    try {
      await markAllAdminNotificationsRead(accessToken);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to mark all notifications as read.");
    } finally {
      setMarkingAll(false);
    }
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  return (
    <>
      <div className="dashboard-header" style={{ marginBottom: 20 }}>
        <div>
          <h2 className="section-title" style={{ margin: 0 }}>
            Notifications
          </h2>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Operational alerts — new restaurants, riders, submitted documents, order issues, payment failures and COD settlements due.
          </p>
        </div>
        <button className="btn-secondary" onClick={handleMarkAllRead} disabled={markingAll || unreadCount === 0}>
          Mark all read {unreadCount > 0 ? `(${unreadCount})` : ""}
        </button>
      </div>

      {error && <ErrorState message={error} onRetry={load} />}

      {loading ? (
        <LoadingIndicator />
      ) : notifications.length === 0 ? (
        <div className="empty-state">No notifications yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Title</th>
                <th>Body</th>
                <th>Received</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {notifications.map((notification) => (
                <tr key={notification.id} style={notification.is_read ? undefined : { fontWeight: 600 }}>
                  <td className="muted">{formatType(notification.type)}</td>
                  <td>{notification.title}</td>
                  <td>{notification.body}</td>
                  <td className="muted">{new Date(notification.created_at).toLocaleString()}</td>
                  <td>
                    <span className={`status-pill ${notification.is_read ? "status-inactive" : "status-active"}`}>
                      {notification.is_read ? "Read" : "Unread"}
                    </span>
                  </td>
                  <td>
                    {!notification.is_read && (
                      <button
                        className="btn-secondary"
                        onClick={() => handleMarkRead(notification)}
                        disabled={actioningId === notification.id}
                      >
                        Mark read
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
