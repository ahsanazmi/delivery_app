import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { LocationMap } from "@/features/location/LocationMap";
import { ApiError } from "@/services/api/apiClient";
import {
  activateAdminRestaurant,
  approveAdminRestaurant,
  deactivateAdminRestaurant,
  getAdminRestaurantDetail,
  reactivateAdminRestaurant,
  rejectAdminRestaurant,
  suspendAdminRestaurant,
  type AdminRestaurantDetail,
} from "@/services/api/adminApi";

export default function RestaurantDetails() {
  const { restaurantId } = useParams<{ restaurantId: string }>();
  const { accessToken } = useSession();
  const { promptText } = useConfirm();
  const toast = useToast();
  const [restaurant, setRestaurant] = useState<AdminRestaurantDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !restaurantId) return;
    setLoading(true);
    setError(null);
    try {
      setRestaurant(await getAdminRestaurantDetail(accessToken, restaurantId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load restaurant.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, restaurantId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleActive() {
    if (!accessToken || !restaurantId || !restaurant) return;
    const deactivating = restaurant.status === "ACTIVE";
    const verb = deactivating ? "deactivate" : "reactivate";
    const reason = await promptText({ title: `Reason to ${verb} ${restaurant.name}`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;

    setUpdating(true);
    try {
      setRestaurant(
        deactivating
          ? await deactivateAdminRestaurant(accessToken, restaurantId, reason.trim())
          : await reactivateAdminRestaurant(accessToken, restaurantId, reason.trim()),
      );
      toast.success(`${restaurant.name} ${deactivating ? "deactivated" : "reactivated"}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update restaurant status.");
    } finally {
      setUpdating(false);
    }
  }

  async function runApprovalAction(action: () => Promise<AdminRestaurantDetail>, successMessage: string) {
    setUpdating(true);
    try {
      setRestaurant(await action());
      toast.success(successMessage);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update restaurant approval.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleApprove() {
    if (!accessToken || !restaurantId || !restaurant) return;
    const reason = await promptText({ title: `Why is ${restaurant.name} being approved?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    await runApprovalAction(() => approveAdminRestaurant(accessToken, restaurantId, reason.trim()), `${restaurant.name} approved.`);
  }

  async function handleReject() {
    if (!accessToken || !restaurantId || !restaurant) return;
    const reason = await promptText({ title: `Why is ${restaurant.name} being rejected?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    await runApprovalAction(() => rejectAdminRestaurant(accessToken, restaurantId, reason.trim()), `${restaurant.name} rejected.`);
  }

  async function handleSuspend() {
    if (!accessToken || !restaurantId || !restaurant) return;
    const reason = await promptText({
      title: `Why is ${restaurant.name} being suspended?`,
      label: "Reason",
      required: true,
    });
    if (!reason || !reason.trim()) return;
    await runApprovalAction(() => suspendAdminRestaurant(accessToken, restaurantId, reason.trim()), `${restaurant.name} suspended.`);
  }

  async function handleActivate() {
    if (!accessToken || !restaurantId || !restaurant) return;
    const reason = await promptText({ title: `Why is ${restaurant.name} being reinstated?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    await runApprovalAction(() => activateAdminRestaurant(accessToken, restaurantId, reason.trim()), `${restaurant.name} reinstated.`);
  }

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !restaurant) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!restaurant) {
    return <div className="empty-state">Restaurant not found.</div>;
  }

  return (
    <>
      <Link to="/restaurants" className="back-link">
        ← Back to restaurants
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">{restaurant.name}</h2>
          <span className={`status-pill status-${restaurant.status.toLowerCase()}`}>{restaurant.status}</span>{" "}
          <span className={`status-pill status-${restaurant.approval_status.toLowerCase()}`}>
            {restaurant.approval_status}
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn-secondary" onClick={toggleActive} disabled={updating}>
            {restaurant.status === "ACTIVE" ? "Deactivate" : "Activate"}
          </button>
          {restaurant.approval_status === "PENDING" && (
            <>
              <button className="btn-secondary" onClick={handleApprove} disabled={updating}>
                Approve
              </button>
              <button className="btn-secondary" onClick={handleReject} disabled={updating}>
                Reject
              </button>
            </>
          )}
          {restaurant.approval_status === "REJECTED" && (
            <button className="btn-secondary" onClick={handleApprove} disabled={updating}>
              Approve
            </button>
          )}
          {restaurant.approval_status === "APPROVED" && (
            <button className="btn-secondary" onClick={handleSuspend} disabled={updating}>
              Suspend
            </button>
          )}
          {restaurant.approval_status === "SUSPENDED" && (
            <button className="btn-secondary" onClick={handleActivate} disabled={updating}>
              Reinstate
            </button>
          )}
        </div>
      </div>

      {restaurant.approval_status === "REJECTED" && restaurant.rejection_reason && (
        <div className="error-banner" role="alert">
          Rejected: {restaurant.rejection_reason}
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Owner</div>
          <div className="value" style={{ fontSize: 16 }}>{restaurant.owner_name}</div>
        </div>
        <div className="stat-card">
          <div className="label">Owner contact</div>
          <div className="value" style={{ fontSize: 13 }}>
            {restaurant.owner_email ?? "—"}
            <br />
            {restaurant.owner_phone ?? "—"}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Restaurant status</div>
          <div className="value" style={{ fontSize: 16 }}>{restaurant.is_open ? "Open" : "Closed"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Rating</div>
          <div className="value">{restaurant.average_rating}</div>
        </div>
        <div className="stat-card">
          <div className="label">Orders</div>
          <div className="value">{restaurant.order_count}</div>
        </div>
        <div className="stat-card">
          <div className="label">Revenue</div>
          <div className="value">₹{restaurant.total_revenue}</div>
        </div>
        <div className="stat-card">
          <div className="label">Created</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(restaurant.created_at).toLocaleDateString()}</div>
        </div>
        {/* Maps & Location System Phase 3 — "Admin should be able to
            inspect the location." Text summary here; the map itself is
            below (Phase 11). */}
        <div className="stat-card">
          <div className="label">Location</div>
          <div className="value" style={{ fontSize: 13 }}>
            {restaurant.address}
            <br />
            {restaurant.latitude}, {restaurant.longitude}
          </div>
        </div>
      </div>

      {/* Maps & Location System Phase 11 — Admin Location Visibility:
          "Restaurant location... where operationally appropriate." Admin
          only ever inspects this — setting/updating it is the restaurant
          owner's own Phase 10 tool, not admin's. */}
      <h2 className="section-title">Location</h2>
      <LocationMap latitude={Number(restaurant.latitude)} longitude={Number(restaurant.longitude)} />

      <h2 className="section-title">Menu</h2>
      {restaurant.menu.length === 0 ? (
        <div className="empty-state">No menu items yet.</div>
      ) : (
        restaurant.menu.map((item) => (
          <div className="order-card" key={item.id}>
            <div className="order-title">{item.name}</div>
            <div className="muted">₹{item.price}</div>
            <div className="muted">{item.is_active ? "Active" : "Inactive"}</div>
          </div>
        ))
      )}

      <h2 className="section-title">Recent orders</h2>
      {restaurant.recent_orders.length === 0 ? (
        <div className="empty-state">No orders yet.</div>
      ) : (
        restaurant.recent_orders.map((order) => (
          <div className="order-card" key={order.id}>
            <div className="order-title">{order.order_number}</div>
            <div className="muted">Customer: {order.customer_name}</div>
            <div className="muted">Status: {order.status}</div>
            <div className="muted">Total: ₹{order.total}</div>
            <div className="muted">{new Date(order.created_at).toLocaleString()}</div>
          </div>
        ))
      )}
    </>
  );
}
