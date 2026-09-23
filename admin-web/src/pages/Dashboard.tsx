import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { getAdminDashboard, type AdminDashboardResponse } from "@/services/api/adminApi";

export default function Dashboard() {
  const { accessToken } = useSession();
  const [data, setData] = useState<AdminDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getAdminDashboard(accessToken));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load admin dashboard.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = data?.summary;

  return (
    <>
      <h2 className="section-title">Overview</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      {loading ? (
        <LoadingIndicator />
      ) : (
        <>
          <div className="stats-grid">
            <div className="stat-card">
              <div className="label">Total customers</div>
              <div className="value">{summary?.total_customers ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Total restaurants</div>
              <div className="value">{summary?.total_restaurants ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Active restaurants</div>
              <div className="value">{summary?.active_restaurants ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Total riders</div>
              <div className="value">{summary?.total_riders ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Active riders</div>
              <div className="value">{summary?.active_riders ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Today's orders</div>
              <div className="value">{summary?.todays_orders ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Today's revenue</div>
              <div className="value">₹{summary?.todays_revenue ?? "0.00"}</div>
            </div>
            <div className="stat-card">
              <div className="label">Pending orders</div>
              <div className="value">{summary?.pending_orders ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Pending rider approvals</div>
              <div className="value">{summary?.pending_rider_approvals ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Pending restaurant approvals</div>
              <div className="value">{summary?.pending_restaurant_approvals ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="label">Pending COD settlement</div>
              <div className="value">₹{summary?.pending_cod_settlement ?? "0.00"}</div>
            </div>
          </div>

          {data && data.alerts.length > 0 && (
            <>
              <h2 className="section-title">Operational alerts</h2>
              {data.alerts.map((alert, index) => (
                <Link
                  to={alert.link}
                  className={`alert-banner alert-${alert.severity}`}
                  key={index}
                  style={{ display: "block", textDecoration: "none", color: "inherit", cursor: "pointer" }}
                >
                  {alert.message}
                </Link>
              ))}
            </>
          )}

          <h2 className="section-title">Recent orders</h2>
          {!data || data.recent_orders.length === 0 ? (
            <div className="empty-state">No orders yet.</div>
          ) : (
            data.recent_orders.map((order) => (
              <div className="order-card" key={order.id}>
                <div className="order-title">{order.order_number}</div>
                <div className="muted">{order.restaurant_name ?? "Walk-in order"}</div>
                <div className="muted">Customer: {order.customer_name}</div>
                <div className="muted">Status: {order.status}</div>
                <div className="muted">Total: ₹{order.total}</div>
              </div>
            ))
          )}

          <h2 className="section-title">Recent registrations</h2>
          {!data || data.recent_registrations.length === 0 ? (
            <div className="empty-state">No registrations yet.</div>
          ) : (
            data.recent_registrations.map((reg) => (
              <div className="order-card" key={reg.id}>
                <div className="order-title">{reg.name}</div>
                <div className="muted">Role: {reg.role}</div>
              </div>
            ))
          )}

          <h2 className="section-title">Pending approvals</h2>
          {!data || data.pending_approvals.length === 0 ? (
            <div className="empty-state">No approvals pending.</div>
          ) : (
            data.pending_approvals.map((approval) => (
              <div className="order-card" key={approval.id}>
                <div className="order-title">{approval.name}</div>
                <div className="muted">{approval.email ?? "No email on file"}</div>
                <div className="muted">Type: {approval.type}</div>
              </div>
            ))
          )}
        </>
      )}
    </>
  );
}
