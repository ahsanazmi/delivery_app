import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  activateAdminRestaurantOwner,
  getAdminRestaurantOwnerDetail,
  suspendAdminRestaurantOwner,
  type AdminRestaurantOwnerSummary,
} from "@/services/api/adminApi";

export default function RestaurantOwnerDetails() {
  const { ownerId } = useParams<{ ownerId: string }>();
  const { accessToken } = useSession();
  const { promptText } = useConfirm();
  const toast = useToast();
  const [owner, setOwner] = useState<AdminRestaurantOwnerSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !ownerId) return;
    setLoading(true);
    setError(null);
    try {
      setOwner(await getAdminRestaurantOwnerDetail(accessToken, ownerId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load restaurant owner.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, ownerId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleStatus() {
    if (!accessToken || !ownerId || !owner) return;
    const suspending = owner.status === "ACTIVE";
    const verb = suspending ? "suspend" : "reactivate";
    const reason = await promptText({
      title: `Reason to ${verb} ${owner.name}`,
      message: "This does not change their restaurant's own status.",
      label: "Reason",
      required: true,
    });
    if (!reason || !reason.trim()) return;

    setUpdating(true);
    try {
      setOwner(
        suspending
          ? await suspendAdminRestaurantOwner(accessToken, ownerId, reason.trim())
          : await activateAdminRestaurantOwner(accessToken, ownerId, reason.trim()),
      );
      toast.success(`${owner.name} ${suspending ? "suspended" : "reactivated"}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update owner status.");
    } finally {
      setUpdating(false);
    }
  }

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !owner) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!owner) {
    return <div className="empty-state">Restaurant owner not found.</div>;
  }

  return (
    <>
      <Link to="/restaurant-owners" className="back-link">
        ← Back to restaurant owners
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">{owner.name}</h2>
          <span className={`status-pill status-${owner.status.toLowerCase()}`}>{owner.status}</span>
        </div>
        <button className="btn-secondary" onClick={toggleStatus} disabled={updating}>
          {owner.status === "ACTIVE" ? "Suspend owner" : "Reactivate owner"}
        </button>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Email</div>
          <div className="value" style={{ fontSize: 16 }}>{owner.email ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Phone</div>
          <div className="value" style={{ fontSize: 16 }}>{owner.phone ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Registered</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(owner.created_at).toLocaleDateString()}</div>
        </div>
        <div className="stat-card">
          <div className="label">Restaurants</div>
          <div className="value">{owner.restaurants.length}</div>
        </div>
      </div>

      <h2 className="section-title">Restaurant association</h2>
      {owner.restaurants.length === 0 ? (
        <div className="empty-state">This owner has no restaurant set up yet.</div>
      ) : (
        owner.restaurants.map((restaurant) => (
          <div className="order-card" key={restaurant.id}>
            <div className="order-title">
              <Link to={`/restaurants/${restaurant.id}`}>{restaurant.name}</Link>
            </div>
            <div className="muted">{restaurant.is_active ? "Active" : "Inactive"}</div>
            <div className="muted">Approval: {restaurant.approval_status}</div>
          </div>
        ))
      )}
    </>
  );
}
