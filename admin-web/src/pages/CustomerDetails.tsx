import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  activateAdminCustomer,
  getAdminCustomerDetail,
  suspendAdminCustomer,
  type AdminCustomerDetail,
} from "@/services/api/adminApi";

export default function CustomerDetails() {
  const { customerId } = useParams<{ customerId: string }>();
  const { accessToken } = useSession();
  const { promptText } = useConfirm();
  const toast = useToast();
  const [customer, setCustomer] = useState<AdminCustomerDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !customerId) return;
    setLoading(true);
    setError(null);
    try {
      setCustomer(await getAdminCustomerDetail(accessToken, customerId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load customer.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, customerId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleStatus() {
    if (!accessToken || !customerId || !customer) return;
    const suspending = customer.status === "ACTIVE";
    const verb = suspending ? "suspend" : "reactivate";
    const reason = await promptText({ title: `Reason to ${verb} ${customer.name}`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;

    setUpdating(true);
    try {
      setCustomer(
        suspending
          ? await suspendAdminCustomer(accessToken, customerId, reason.trim())
          : await activateAdminCustomer(accessToken, customerId, reason.trim()),
      );
      toast.success(`${customer.name} ${suspending ? "suspended" : "reactivated"}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update customer status.");
    } finally {
      setUpdating(false);
    }
  }

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !customer) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!customer) {
    return <div className="empty-state">Customer not found.</div>;
  }

  return (
    <>
      <Link to="/customers" className="back-link">
        ← Back to customers
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">{customer.name}</h2>
          <span className={`status-pill status-${customer.status.toLowerCase()}`}>{customer.status}</span>
        </div>
        <button className="btn-secondary" onClick={toggleStatus} disabled={updating}>
          {customer.status === "ACTIVE" ? "Suspend customer" : "Reactivate customer"}
        </button>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Email</div>
          <div className="value" style={{ fontSize: 16 }}>{customer.email ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Phone</div>
          <div className="value" style={{ fontSize: 16 }}>{customer.phone ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Registered</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(customer.created_at).toLocaleDateString()}</div>
        </div>
        <div className="stat-card">
          <div className="label">Total orders</div>
          <div className="value">{customer.order_count}</div>
        </div>
        <div className="stat-card">
          <div className="label">Total spending</div>
          <div className="value">₹{customer.total_spending}</div>
        </div>
      </div>

      <h2 className="section-title">Order history</h2>
      {customer.recent_orders.length === 0 ? (
        <div className="empty-state">This customer hasn't placed any orders yet.</div>
      ) : (
        customer.recent_orders.map((order) => (
          <div className="order-card" key={order.id}>
            <div className="order-title">{order.order_number}</div>
            <div className="muted">{order.restaurant_name ?? "Walk-in order"}</div>
            <div className="muted">Status: {order.status}</div>
            <div className="muted">Total: ₹{order.total}</div>
            <div className="muted">{new Date(order.created_at).toLocaleString()}</div>
          </div>
        ))
      )}
    </>
  );
}
