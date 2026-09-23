import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { getAdminPaymentDetail, type AdminPaymentDetail } from "@/services/api/adminApi";

function statusPillClass(status: string) {
  if (status === "PAID") return "status-approved";
  if (status === "FAILED" || status === "CANCELLED") return "status-rejected";
  if (status === "REFUNDED" || status === "REFUND_PENDING" || status === "PARTIALLY_REFUNDED") return "status-suspended";
  return "status-pending";
}

export default function PaymentDetails() {
  const { paymentId } = useParams<{ paymentId: string }>();
  const { accessToken } = useSession();
  const [payment, setPayment] = useState<AdminPaymentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !paymentId) return;
    setLoading(true);
    setError(null);
    try {
      setPayment(await getAdminPaymentDetail(accessToken, paymentId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load payment.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, paymentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error && !payment) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!payment) {
    return <div className="empty-state">Payment not found.</div>;
  }

  return (
    <>
      <Link to="/payments" className="back-link">
        ← Back to payments
      </Link>

      {error && <ErrorState message={error} onRetry={load} />}

      <div className="detail-header">
        <div>
          <h2 className="section-title">Payment {payment.id.slice(0, 8)}</h2>
          <span className={`status-pill ${statusPillClass(payment.status)}`}>{payment.status.replaceAll("_", " ")}</span>
        </div>
      </div>

      {payment.failure_reason && (
        <div className="error-banner" role="alert">
          Failure reason: {payment.failure_reason}
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Order</div>
          <div className="value" style={{ fontSize: 16 }}>
            <Link to={`/orders/${payment.order_id}`}>{payment.order_number}</Link>
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Customer</div>
          <div className="value" style={{ fontSize: 13 }}>
            {payment.customer_name}
            <br />
            {payment.customer_email}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Amount</div>
          <div className="value">
            {payment.currency} {payment.amount}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Method</div>
          <div className="value" style={{ fontSize: 16 }}>{payment.method === "cod" ? "Cash on delivery" : "Online"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Provider</div>
          <div className="value" style={{ fontSize: 16 }}>{payment.provider ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Provider reference</div>
          <div className="value" style={{ fontSize: 14 }}>{payment.transaction_reference ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Verified</div>
          <div className="value" style={{ fontSize: 16 }}>{payment.is_verified ? "Yes" : "No"}</div>
        </div>
        <div className="stat-card">
          <div className="label">Paid at</div>
          <div className="value" style={{ fontSize: 16 }}>{payment.paid_at ? new Date(payment.paid_at).toLocaleString() : "—"}</div>
        </div>
        {payment.method === "cod" && (
          <>
            <div className="stat-card">
              <div className="label">Collected by</div>
              <div className="value" style={{ fontSize: 16 }}>{payment.collected_by_rider_name ?? "Not yet collected"}</div>
            </div>
            <div className="stat-card">
              <div className="label">Collected at</div>
              <div className="value" style={{ fontSize: 16 }}>
                {payment.collected_at ? new Date(payment.collected_at).toLocaleString() : "—"}
              </div>
            </div>
          </>
        )}
        {payment.latest_refund_status && (
          <div className="stat-card">
            <div className="label">Refund status</div>
            <div className="value" style={{ fontSize: 16 }}>{payment.latest_refund_status}</div>
          </div>
        )}
        <div className="stat-card">
          <div className="label">Created</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(payment.created_at).toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="label">Last updated</div>
          <div className="value" style={{ fontSize: 16 }}>{new Date(payment.updated_at).toLocaleString()}</div>
        </div>
      </div>
    </>
  );
}
