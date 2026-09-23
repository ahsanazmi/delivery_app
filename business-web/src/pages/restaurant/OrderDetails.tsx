import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  acceptOrder,
  getRestaurantOrder,
  markOrderPreparing,
  markOrderReady,
  rejectOrder,
  type OrderDetail,
} from "@/services/api/ordersApi";
import { rupees } from "@/utils/currency";

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

// The full order lifecycle the restaurant can see end-to-end. Only the first
// four stages are ones the restaurant actually drives (accept/reject, start
// preparing, mark ready); everything from "Rider assigned" onward belongs to
// the delivery workflow — the restaurant portal never gets a button for those,
// it can only watch them happen.
const LIFECYCLE_STAGES: { status: string; label: string; ownedByDelivery?: boolean }[] = [
  { status: "placed", label: "Placed" },
  { status: "confirmed", label: "Confirmed" },
  { status: "preparing", label: "Preparing" },
  { status: "ready_for_pickup", label: "Ready for pickup" },
  { status: "rider_assigned", label: "Rider assigned", ownedByDelivery: true },
  { status: "picked_up", label: "Picked up", ownedByDelivery: true },
  { status: "out_for_delivery", label: "Out for delivery", ownedByDelivery: true },
  { status: "delivered", label: "Delivered", ownedByDelivery: true },
];

const TERMINAL_NON_LIFECYCLE_STATUSES = new Set(["rejected", "cancelled"]);

export default function OrderDetailsPage() {
  const { accessToken } = useSession();
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken || !orderId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getRestaurantOrder(accessToken, orderId);
      setOrder(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load this order.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, orderId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleAccept() {
    if (!accessToken || !orderId) return;
    setDecisionBusy(true);
    setError(null);
    try {
      const updated = await acceptOrder(accessToken, orderId);
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to accept this order.");
    } finally {
      setDecisionBusy(false);
    }
  }

  async function handleReject() {
    if (!accessToken || !orderId) return;
    const reason = window.prompt("Reason for rejecting this order (optional):");
    if (reason === null) return; // user cancelled the prompt — don't reject

    setDecisionBusy(true);
    setError(null);
    try {
      const updated = await rejectOrder(accessToken, orderId, reason || undefined);
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to reject this order.");
    } finally {
      setDecisionBusy(false);
    }
  }

  async function handleMarkPreparing() {
    if (!accessToken || !orderId) return;
    setDecisionBusy(true);
    setError(null);
    try {
      const updated = await markOrderPreparing(accessToken, orderId);
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to update this order.");
    } finally {
      setDecisionBusy(false);
    }
  }

  async function handleMarkReady() {
    if (!accessToken || !orderId) return;
    setDecisionBusy(true);
    setError(null);
    try {
      const updated = await markOrderReady(accessToken, orderId);
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to update this order.");
    } finally {
      setDecisionBusy(false);
    }
  }

  if (loading) {
    return <p className="page-center">Loading order…</p>;
  }

  if (error && !order) {
    return (
      <div className="error-banner" role="alert">
        {error}
        <button className="btn-secondary" style={{ marginLeft: 12 }} onClick={() => load()}>
          Try again
        </button>
      </div>
    );
  }

  if (!order) return null;

  return (
    <div className="order-details-page">
      <div className="dashboard-toolbar">
        <h2 className="section-title" style={{ margin: 0 }}>
          Order #{order.order_number}
        </h2>
        <button className="btn-secondary" onClick={() => navigate("/orders")}>
          Back to orders
        </button>
      </div>

      <div className={`status-card status-${order.status === "delivered" ? "open" : "closed"}`} style={{ marginBottom: 20 }}>
        <div>
          <div className="status-name">Status</div>
          <div className="status-badge">{statusLabel(order.status).toUpperCase()}</div>
        </div>
        <div className="muted">Placed {new Date(order.created_at).toLocaleString()}</div>
      </div>

      {!TERMINAL_NON_LIFECYCLE_STATUSES.has(order.status) && (
        <div className="lifecycle-track" style={{ marginBottom: 20 }}>
          {LIFECYCLE_STAGES.map((stage, index) => {
            const currentIndex = LIFECYCLE_STAGES.findIndex((s) => s.status === order.status);
            const state = index < currentIndex ? "done" : index === currentIndex ? "current" : "upcoming";
            return (
              <div className={`lifecycle-step lifecycle-step-${state}`} key={stage.status}>
                <div className="lifecycle-step-dot" />
                <div className="lifecycle-step-label">
                  {stage.label}
                  {stage.ownedByDelivery && <div className="lifecycle-step-owner">Delivery</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {order.status === "placed" && (
        <div className="profile-form-actions" style={{ justifyContent: "flex-start", marginBottom: 20 }}>
          <button className="btn-primary" style={{ width: "auto", padding: "0 24px" }} onClick={handleAccept} disabled={decisionBusy}>
            {decisionBusy ? "Please wait…" : "Accept order"}
          </button>
          <button className="btn-secondary btn-danger" onClick={handleReject} disabled={decisionBusy}>
            Reject order
          </button>
        </div>
      )}

      {order.status === "rejected" && order.cancelled_reason && (
        <div className="error-banner" style={{ marginBottom: 20 }}>
          Rejected: {order.cancelled_reason}
        </div>
      )}

      {order.status === "confirmed" && (
        <div className="profile-form-actions" style={{ justifyContent: "flex-start", marginBottom: 20 }}>
          <button className="btn-primary" style={{ width: "auto", padding: "0 24px" }} onClick={handleMarkPreparing} disabled={decisionBusy}>
            {decisionBusy ? "Please wait…" : "Start preparing"}
          </button>
        </div>
      )}

      {order.status === "preparing" && (
        <div className="profile-form-actions" style={{ justifyContent: "flex-start", marginBottom: 20 }}>
          <button className="btn-primary" style={{ width: "auto", padding: "0 24px" }} onClick={handleMarkReady} disabled={decisionBusy}>
            {decisionBusy ? "Please wait…" : "Mark ready for pickup"}
          </button>
        </div>
      )}

      {order.status === "ready_for_pickup" && (
        <div className="success-banner" style={{ marginBottom: 20 }}>
          ✓ Ready for pickup — waiting for rider…
        </div>
      )}

      <div className="profile-view-grid" style={{ marginBottom: 20 }}>
        <div className="profile-field">
          <div className="profile-field-label">Customer</div>
          <div className="profile-field-value">{order.customer_name}</div>
        </div>
        <div className="profile-field">
          <div className="profile-field-label">Phone</div>
          <div className="profile-field-value">{order.customer_phone || "—"}</div>
        </div>
        <div className="profile-field">
          <div className="profile-field-label">Delivery address</div>
          <div className="profile-field-value">
            {order.address_line}, {order.city}
            {order.state ? `, ${order.state}` : ""} {order.postal_code}
            {order.landmark && <div className="muted">Landmark: {order.landmark}</div>}
          </div>
        </div>
        <div className="profile-field">
          <div className="profile-field-label">Delivery instructions</div>
          <div className="profile-field-value">{order.delivery_instructions || "—"}</div>
        </div>
        <div className="profile-field">
          <div className="profile-field-label">Payment method</div>
          <div className="profile-field-value">
            {order.payment_method.toUpperCase()} · {order.payment_status.replace(/_/g, " ")}
          </div>
        </div>
        <div className="profile-field">
          <div className="profile-field-label">Order timestamp</div>
          <div className="profile-field-value">{new Date(order.created_at).toLocaleString()}</div>
        </div>
      </div>

      <h3 className="section-title" style={{ fontSize: 17 }}>
        Items
      </h3>
      <div className="order-list" style={{ marginBottom: 20 }}>
        {order.items.map((item) => (
          <div className="order-row" key={item.id}>
            <div className="order-row-main">
              <span className="order-number">{item.product_name}</span>
              <span className="muted">
                {item.quantity} × {rupees(item.unit_price)}
              </span>
            </div>
            <div className="order-row-meta">
              <span>Line total: {rupees(Number(item.unit_price) * item.quantity)}</span>
            </div>
          </div>
        ))}
      </div>

      <h3 className="section-title" style={{ fontSize: 17 }}>
        Bill summary
      </h3>
      <div className="profile-form" style={{ marginBottom: 20 }}>
        <div className="summary-line">
          <span>Subtotal</span>
          <span>{rupees(order.subtotal)}</span>
        </div>
        <div className="summary-line">
          <span>Delivery fee</span>
          <span>{rupees(order.delivery_fee)}</span>
        </div>
        <div className="summary-line">
          <span>Tax</span>
          <span>{rupees(order.tax)}</span>
        </div>
        {Number(order.discount) > 0 && (
          <div className="summary-line">
            <span>Discount</span>
            <span>-{rupees(order.discount)}</span>
          </div>
        )}
        <div className="summary-line summary-line-total">
          <span>Total</span>
          <span>{rupees(order.total)}</span>
        </div>
      </div>

      <h3 className="section-title" style={{ fontSize: 17 }}>
        Your earnings
      </h3>
      <div className="profile-form" style={{ marginBottom: 20 }}>
        <div className="summary-line">
          <span>Order amount</span>
          <span>{rupees(order.total)}</span>
        </div>
        <div className="summary-line">
          <span>Restaurant earning</span>
          <span>{rupees(order.restaurant_earning)}</span>
        </div>
        <div className="summary-line">
          <span>Commission</span>
          <span>-{rupees(order.commission)}</span>
        </div>
        <div className="summary-line summary-line-total">
          <span>Net amount</span>
          <span>{rupees(order.net_amount)}</span>
        </div>
      </div>

      <h3 className="section-title" style={{ fontSize: 17 }}>
        Status history
      </h3>
      <div className="order-list">
        {order.status_history.map((entry) => (
          <div className="order-row" key={entry.id}>
            <div className="order-row-main">
              <span className="order-number">{statusLabel(entry.status)}</span>
              <span className="muted">{new Date(entry.created_at).toLocaleString()}</span>
            </div>
            {entry.note && <div className="order-row-meta">{entry.note}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
