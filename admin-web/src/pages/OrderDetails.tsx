import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  cancelAdminOrder,
  getAdminOrderDetail,
  getAdminRiders,
  reassignAdminOrderRider,
  type AdminOrderDetail,
} from "@/services/api/adminApi";

const CANCELLABLE_STATUSES = ["placed", "confirmed", "preparing", "ready_for_pickup", "rider_assigned"];
const REASSIGNABLE_STATUSES = ["rider_assigned"];

export default function OrderDetails() {
  const { orderId } = useParams<{ orderId: string }>();
  const { accessToken } = useSession();
  const { confirm, promptText } = useConfirm();
  const toast = useToast();
  const [order, setOrder] = useState<AdminOrderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actioning, setActioning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !orderId) return;
    setLoading(true);
    setError(null);
    try {
      setOrder(await getAdminOrderDetail(accessToken, orderId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load order.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, orderId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCancel() {
    if (!order || !accessToken || !orderId) return;
    const reason = await promptText({ title: `Why is order ${order.order_number} being cancelled?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    const ok = await confirm({ title: `Cancel order ${order.order_number}?`, message: "This cannot be undone.", confirmLabel: "Cancel order", danger: true });
    if (!ok) return;

    setActioning(true);
    try {
      await cancelAdminOrder(accessToken, orderId, reason.trim());
      toast.success(`Order ${order.order_number} cancelled.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to cancel order.");
    } finally {
      setActioning(false);
    }
  }

  async function handleReassign() {
    if (!order || !accessToken || !orderId) return;
    const query = await promptText({ title: "Reassign rider", label: "Search by name, email, or phone", required: true });
    if (!query || !query.trim()) return;

    setActioning(true);
    try {
      const matches = await getAdminRiders(accessToken, { search: query.trim(), limit: 5 });
      if (matches.items.length === 0) {
        toast.error(`No rider found matching "${query}".`);
        return;
      }
      if (matches.items.length > 1) {
        toast.error(`Multiple riders match "${query}" — search more specifically (e.g. by phone or email).`);
        return;
      }
      const newRider = matches.items[0];
      const ok = await confirm({ title: `Reassign order ${order.order_number} to ${newRider.name}?` });
      if (!ok) return;
      const reason = await promptText({ title: "Reason for reassignment", label: "Reason", required: true });
      if (!reason || !reason.trim()) return;

      await reassignAdminOrderRider(accessToken, orderId, newRider.id, reason.trim());
      toast.success(`Order ${order.order_number} reassigned to ${newRider.name}.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to reassign rider.");
    } finally {
      setActioning(false);
    }
  }

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !order) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!order) {
    return <div className="empty-state">Order not found.</div>;
  }

  return (
    <>
      <Link to="/orders" className="back-link">
        ← Back to orders
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">{order.order_number}</h2>
          <span className="status-pill status-approved">{order.status.replaceAll("_", " ")}</span>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {REASSIGNABLE_STATUSES.includes(order.status) && (
            <button className="btn-secondary" onClick={handleReassign} disabled={actioning}>
              Reassign rider
            </button>
          )}
          {CANCELLABLE_STATUSES.includes(order.status) && (
            <button className="btn-secondary" onClick={handleCancel} disabled={actioning}>
              Cancel order
            </button>
          )}
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Customer</div>
          <div className="value" style={{ fontSize: 16 }}>{order.customer_name}</div>
        </div>
        <div className="stat-card">
          <div className="label">Customer contact</div>
          <div className="value" style={{ fontSize: 13 }}>
            {order.customer_email}
            <br />
            {order.customer_phone ?? "—"}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Restaurant</div>
          <div className="value" style={{ fontSize: 16 }}>{order.restaurant_name ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Rider</div>
          <div className="value" style={{ fontSize: 16 }}>{order.rider_name ?? "Not assigned"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Payment</div>
          <div className="value" style={{ fontSize: 16 }}>
            {order.payment_method} · {order.payment_status}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Placed</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(order.created_at).toLocaleString()}</div>
        </div>
      </div>

      <h2 className="section-title">Items</h2>
      {order.items.length === 0 ? (
        <div className="empty-state">No items on this order.</div>
      ) : (
        order.items.map((item) => (
          <div className="order-card" key={item.id}>
            <div className="order-title">{item.product_name}</div>
            <div className="muted">
              {item.quantity} × ₹{item.unit_price}
            </div>
          </div>
        ))
      )}

      <h2 className="section-title">Bill breakdown</h2>
      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Subtotal</div>
          <div className="value">₹{order.subtotal}</div>
        </div>
        <div className="stat-card">
          <div className="label">Delivery fee</div>
          <div className="value">₹{order.delivery_fee}</div>
        </div>
        <div className="stat-card">
          <div className="label">Tax</div>
          <div className="value">₹{order.tax}</div>
        </div>
        <div className="stat-card">
          <div className="label">Discount</div>
          <div className="value">₹{order.discount}</div>
        </div>
        <div className="stat-card">
          <div className="label">Total</div>
          <div className="value">₹{order.total}</div>
        </div>
      </div>

      <h2 className="section-title">Timeline</h2>
      {order.status_history.length === 0 ? (
        <div className="empty-state">No status history yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Note</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {order.status_history.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.status.replaceAll("_", " ")}</td>
                  <td className="muted">{entry.note ?? "—"}</td>
                  <td className="muted">{new Date(entry.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
