import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { getAdminDeliveryAssignmentDetail, type AdminDeliveryAssignmentDetail } from "@/services/api/adminApi";

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function DeliveryAssignmentDetails() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const { accessToken } = useSession();
  const [assignment, setAssignment] = useState<AdminDeliveryAssignmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !assignmentId) return;
    setLoading(true);
    setError(null);
    try {
      setAssignment(await getAdminDeliveryAssignmentDetail(accessToken, assignmentId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load delivery assignment.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, assignmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !assignment) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!assignment) {
    return <div className="empty-state">Delivery assignment not found.</div>;
  }

  const timeline = [
    { label: "Accepted", value: assignment.accepted_at },
    { label: "Arrived at restaurant", value: assignment.arrived_at },
    { label: "Picked up", value: assignment.picked_up_at },
    { label: "Out for delivery", value: assignment.out_for_delivery_at },
    { label: "Delivered", value: assignment.delivered_at },
    { label: "Rejected", value: assignment.rejected_at },
    { label: "Cancelled", value: assignment.cancelled_at },
  ].filter((entry) => entry.value);

  return (
    <>
      <Link to="/delivery-assignments" className="back-link">
        ← Back to delivery assignments
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">{assignment.order_number}</h2>
          <span className="status-pill status-approved">{assignment.status.replaceAll("_", " ")}</span>
        </div>
      </div>

      {assignment.rejection_reason && (
        <div className="error-banner" role="alert">
          Rejected: {assignment.rejection_reason}
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Order</div>
          <div className="value" style={{ fontSize: 16 }}>
            <Link to={`/orders/${assignment.order_id}`}>{assignment.order_number}</Link>
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Rider</div>
          <div className="value" style={{ fontSize: 16 }}>{assignment.rider_name ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Restaurant</div>
          <div className="value" style={{ fontSize: 16 }}>{assignment.restaurant_name ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Customer</div>
          <div className="value" style={{ fontSize: 16 }}>{assignment.customer_name ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Assignment created</div>
          <div className="value" style={{ fontSize: 16 }}>{formatTime(assignment.created_at)}</div>
        </div>
      </div>

      <h2 className="section-title">Timeline</h2>
      {timeline.length === 0 ? (
        <div className="empty-state">No timeline events recorded yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {timeline.map((entry) => (
                <tr key={entry.label}>
                  <td>{entry.label}</td>
                  <td className="muted">{formatTime(entry.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
