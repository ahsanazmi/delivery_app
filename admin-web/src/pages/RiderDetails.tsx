import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  approveAdminRiderDocument,
  deactivateAdminRider,
  getAdminRiderDetail,
  reactivateAdminRider,
  rejectAdminRiderDocument,
  updateAdminRiderApproval,
  type AdminRiderDetail,
  type AdminRiderDocument,
} from "@/services/api/adminApi";

const NAMED_DOCUMENT_TYPES = ["DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT"] as const;

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  DRIVING_LICENSE: "Driving License",
  VEHICLE_REGISTRATION: "Vehicle Registration",
  IDENTITY_DOCUMENT: "Identity Document",
  BANK_DOCUMENT: "Bank Document",
  PROFILE_PHOTO: "Profile Photo",
};

export default function RiderDetails() {
  const { riderId } = useParams<{ riderId: string }>();
  const { accessToken } = useSession();
  const { promptText } = useConfirm();
  const toast = useToast();
  const [rider, setRider] = useState<AdminRiderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !riderId) return;
    setLoading(true);
    setError(null);
    try {
      setRider(await getAdminRiderDetail(accessToken, riderId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load rider.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, riderId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runAction(action: "approve" | "reject" | "suspend" | "activate", reason: string) {
    if (!accessToken || !riderId) return;
    setUpdating(true);
    try {
      setRider(await updateAdminRiderApproval(accessToken, riderId, action, reason));
      toast.success(`Rider ${action}d.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update rider approval.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleApprove() {
    if (!rider) return;
    const reason = await promptText({ title: `Why is ${rider.name} being approved?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    await runAction("approve", reason.trim());
  }

  async function handleReject() {
    if (!rider) return;
    const reason = await promptText({ title: `Why is ${rider.name} being rejected?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    await runAction("reject", reason.trim());
  }

  async function handleSuspend() {
    if (!rider) return;
    const reason = await promptText({
      title: `Why is ${rider.name} being suspended?`,
      label: "Reason",
      required: true,
    });
    if (!reason || !reason.trim()) return;
    await runAction("suspend", reason.trim());
  }

  async function handleActivate() {
    if (!rider) return;
    const reason = await promptText({ title: `Why is ${rider.name} being reinstated?`, label: "Reason", required: true });
    if (!reason || !reason.trim()) return;
    await runAction("activate", reason.trim());
  }

  // Phase 23 — the account-level on/off switch (User.is_active), distinct
  // from the approval_status actions above (delivery eligibility only).
  async function handleToggleAccount() {
    if (!accessToken || !riderId || !rider) return;
    const deactivating = rider.is_active;
    const verb = deactivating ? "deactivate" : "reactivate";
    const reason = await promptText({
      title: `Reason to ${verb} ${rider.name}'s account`,
      message: "This is separate from approval status and blocks login entirely.",
      label: "Reason",
      required: true,
    });
    if (!reason || !reason.trim()) return;

    setUpdating(true);
    try {
      setRider(
        deactivating
          ? await deactivateAdminRider(accessToken, riderId, reason.trim())
          : await reactivateAdminRider(accessToken, riderId, reason.trim()),
      );
      toast.success(`${rider.name}'s account ${deactivating ? "deactivated" : "reactivated"}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update rider account status.");
    } finally {
      setUpdating(false);
    }
  }

  function replaceDocument(updated: AdminRiderDocument) {
    setRider((current) =>
      current ? { ...current, documents: current.documents.map((d) => (d.id === updated.id ? updated : d)) } : current,
    );
  }

  async function handleApproveDocument(document: AdminRiderDocument) {
    if (!accessToken || !riderId) return;
    setUpdating(true);
    try {
      replaceDocument(await approveAdminRiderDocument(accessToken, riderId, document.id));
      toast.success("Document approved.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to approve document.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleRejectDocument(document: AdminRiderDocument) {
    if (!accessToken || !riderId) return;
    const reason = await promptText({
      title: `Why is this ${DOCUMENT_TYPE_LABELS[document.document_type] ?? document.document_type} being rejected?`,
      label: "Reason",
      required: true,
    });
    if (!reason || !reason.trim()) return;
    setUpdating(true);
    try {
      replaceDocument(await rejectAdminRiderDocument(accessToken, riderId, document.id, reason.trim()));
      toast.success("Document rejected.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to reject document.");
    } finally {
      setUpdating(false);
    }
  }

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !rider) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!rider) {
    return <div className="empty-state">Rider not found.</div>;
  }

  return (
    <>
      <Link to="/riders" className="back-link">
        ← Back to riders
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">{rider.name}</h2>
          <span className={`status-pill status-${rider.approval_status.toLowerCase()}`}>{rider.approval_status}</span>{" "}
          <span className={`status-pill status-${rider.is_online ? "approved" : "inactive"}`}>
            {rider.is_online ? "Online" : "Offline"}
          </span>{" "}
          <span className={`status-pill ${rider.is_active ? "status-active" : "status-inactive"}`}>
            {rider.is_active ? "Account active" : "Account deactivated"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn-secondary" onClick={handleToggleAccount} disabled={updating}>
            {rider.is_active ? "Deactivate account" : "Reactivate account"}
          </button>
          {rider.approval_status === "PENDING" && (
            <>
              <button className="btn-secondary" onClick={handleApprove} disabled={updating}>
                Approve
              </button>
              <button className="btn-secondary" onClick={handleReject} disabled={updating}>
                Reject
              </button>
            </>
          )}
          {rider.approval_status === "REJECTED" && (
            <button className="btn-secondary" onClick={handleApprove} disabled={updating}>
              Approve
            </button>
          )}
          {rider.approval_status === "APPROVED" && (
            <button className="btn-secondary" onClick={handleSuspend} disabled={updating}>
              Suspend
            </button>
          )}
          {rider.approval_status === "SUSPENDED" && (
            <button className="btn-secondary" onClick={handleActivate} disabled={updating}>
              Reinstate
            </button>
          )}
        </div>
      </div>

      {rider.approval_status === "REJECTED" && rider.rejection_reason && (
        <div className="error-banner" role="alert">
          Rejected: {rider.rejection_reason}
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Phone</div>
          <div className="value" style={{ fontSize: 16 }}>{rider.phone ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Email</div>
          <div className="value" style={{ fontSize: 16 }}>{rider.email ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Vehicle</div>
          <div className="value" style={{ fontSize: 16 }}>
            {rider.vehicle_type ? `${rider.vehicle_type}${rider.vehicle_number ? ` · ${rider.vehicle_number}` : ""}` : "Not set"}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Rating</div>
          <div className="value">{rider.rating > 0 ? rider.rating.toFixed(2) : "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Deliveries</div>
          <div className="value">{rider.deliveries_count}</div>
        </div>
        <div className="stat-card">
          <div className="label">Earnings</div>
          <div className="value">₹{rider.total_earnings}</div>
        </div>
        <div className="stat-card">
          <div className="label">Registered</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(rider.created_at).toLocaleDateString()}</div>
        </div>
      </div>

      <h2 className="section-title">Documents</h2>
      {NAMED_DOCUMENT_TYPES.map((type) => {
        const doc = rider.documents.find((d) => d.document_type === type);
        return (
          <DocumentCard
            key={type}
            label={DOCUMENT_TYPE_LABELS[type]}
            document={doc}
            updating={updating}
            onApprove={handleApproveDocument}
            onReject={handleRejectDocument}
          />
        );
      })}

      {rider.documents.filter((d) => !(NAMED_DOCUMENT_TYPES as readonly string[]).includes(d.document_type)).length > 0 && (
        <>
          <h2 className="section-title">Other required documents</h2>
          {rider.documents
            .filter((d) => !(NAMED_DOCUMENT_TYPES as readonly string[]).includes(d.document_type))
            .map((doc) => (
              <DocumentCard
                key={doc.id}
                label={DOCUMENT_TYPE_LABELS[doc.document_type] ?? doc.document_type.replaceAll("_", " ")}
                document={doc}
                updating={updating}
                onApprove={handleApproveDocument}
                onReject={handleRejectDocument}
              />
            ))}
        </>
      )}

      <h2 className="section-title">Delivery history</h2>
      {rider.recent_deliveries.length === 0 ? (
        <div className="empty-state">No deliveries yet.</div>
      ) : (
        rider.recent_deliveries.map((delivery) => (
          <div className="order-card" key={delivery.id}>
            <div className="order-title">{delivery.order_number}</div>
            <div className="muted">{delivery.restaurant_name ?? "Walk-in order"}</div>
            <div className="muted">Status: {delivery.status}</div>
            <div className="muted">Total: ₹{delivery.total}</div>
            <div className="muted">{new Date(delivery.created_at).toLocaleString()}</div>
          </div>
        ))
      )}
    </>
  );
}

function DocumentCard({
  label,
  document,
  updating,
  onApprove,
  onReject,
}: {
  label: string;
  document: AdminRiderDocument | undefined;
  updating: boolean;
  onApprove: (document: AdminRiderDocument) => void;
  onReject: (document: AdminRiderDocument) => void;
}) {
  if (!document) {
    return (
      <div className="order-card">
        <div className="order-title">{label}</div>
        <div className="muted">Not uploaded yet.</div>
      </div>
    );
  }

  const canApprove = document.verification_status === "PENDING" || document.verification_status === "REJECTED";
  const canReject = document.verification_status === "PENDING" || document.verification_status === "APPROVED";

  return (
    <div className="order-card">
      <div className="order-title">{label}</div>
      <div className="muted">
        <span className={`status-pill status-${document.verification_status.toLowerCase()}`}>
          {document.verification_status}
        </span>
      </div>
      {document.rejection_reason && <div className="muted">Rejected: {document.rejection_reason}</div>}
      <div className="order-actions">
        {canApprove && (
          <button className="btn-secondary" onClick={() => onApprove(document)} disabled={updating}>
            Approve
          </button>
        )}
        {canReject && (
          <button className="btn-secondary" onClick={() => onReject(document)} disabled={updating}>
            Reject
          </button>
        )}
      </div>
    </div>
  );
}
