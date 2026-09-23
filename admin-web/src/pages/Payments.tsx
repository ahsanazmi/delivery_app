import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminPayments,
  type AdminPaymentListResponse,
  type AdminPaymentMethodValue,
  type AdminPaymentStatusValue,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

const STATUS_OPTIONS: AdminPaymentStatusValue[] = [
  "PENDING",
  "PROCESSING",
  "PAID",
  "FAILED",
  "REFUND_PENDING",
  "PARTIALLY_REFUNDED",
  "REFUNDED",
  "CANCELLED",
];

function statusPillClass(status: AdminPaymentStatusValue) {
  if (status === "PAID") return "status-approved";
  if (status === "FAILED" || status === "CANCELLED") return "status-rejected";
  if (status === "REFUNDED" || status === "REFUND_PENDING" || status === "PARTIALLY_REFUNDED") return "status-suspended";
  return "status-pending";
}

export default function Payments() {
  const { accessToken } = useSession();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<AdminPaymentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [method, setMethod] = useState<AdminPaymentMethodValue | "">("");
  // Phase 24 — deep-linked from the "payments failed today" dashboard alert.
  const [status, setStatus] = useState<AdminPaymentStatusValue | "">(
    () => (searchParams.get("status") as AdminPaymentStatusValue | null) ?? "",
  );
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  // Admin Payment Management (Phase 27) — dedicated Order ID / Customer
  // filters, additive alongside the generic search box above (which still
  // covers transaction-reference lookups these two don't).
  const [orderNumber, setOrderNumber] = useState("");
  const [orderNumberInput, setOrderNumberInput] = useState("");
  const [customer, setCustomer] = useState("");
  const [customerInput, setCustomerInput] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminPayments(accessToken, {
          search: search || undefined,
          method: method || undefined,
          status: status || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          order_number: orderNumber || undefined,
          customer: customer || undefined,
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load payments.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, method, status, dateFrom, dateTo, orderNumber, customer, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
    setOrderNumber(orderNumberInput.trim());
    setCustomer(customerInput.trim());
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <>
      <h2 className="section-title">Payments</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search order #, customer, transaction ref…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <input
          className="filter-input"
          type="text"
          placeholder="Order ID"
          value={orderNumberInput}
          onChange={(e) => setOrderNumberInput(e.target.value)}
          style={{ minWidth: 140 }}
        />
        <input
          className="filter-input"
          type="text"
          placeholder="Customer"
          value={customerInput}
          onChange={(e) => setCustomerInput(e.target.value)}
          style={{ minWidth: 160 }}
        />
        <select
          className="filter-input"
          value={method}
          onChange={(e) => {
            setMethod(e.target.value as AdminPaymentMethodValue | "");
            setPage(1);
          }}
        >
          <option value="">Any method</option>
          <option value="cod">Cash on delivery</option>
          <option value="razorpay">Online (Razorpay)</option>
        </select>
        <select
          className="filter-input"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AdminPaymentStatusValue | "");
            setPage(1);
          }}
        >
          <option value="">Any status</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <label className="filter-date-label">
          From
          <input
            className="filter-input"
            type="date"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <label className="filter-date-label">
          To
          <input
            className="filter-input"
            type="date"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No payments match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Payment ID</th>
                  <th>Order</th>
                  <th>Customer</th>
                  <th>Amount</th>
                  <th>Method</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Provider reference</th>
                  <th>Created</th>
                  <th>Paid</th>
                  <th>Refund status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((payment) => (
                  <tr key={payment.id}>
                    <td>
                      <Link to={`/payments/${payment.id}`}>{payment.id.slice(0, 8)}</Link>
                    </td>
                    <td className="muted">
                      <Link to={`/orders/${payment.order_id}`}>{payment.order_number}</Link>
                    </td>
                    <td className="muted">{payment.customer_name}</td>
                    <td>₹{payment.amount}</td>
                    <td className="muted">{payment.method === "cod" ? "Cash on delivery" : "Online"}</td>
                    <td className="muted">{payment.provider ?? "—"}</td>
                    <td>
                      <span className={`status-pill ${statusPillClass(payment.status)}`}>{payment.status.replaceAll("_", " ")}</span>
                    </td>
                    <td className="muted">{payment.transaction_reference ?? "—"}</td>
                    <td className="muted">{new Date(payment.created_at).toLocaleString()}</td>
                    <td className="muted">{payment.paid_at ? new Date(payment.paid_at).toLocaleString() : "—"}</td>
                    <td className="muted">{payment.latest_refund_status ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination-bar">
            <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span className="muted">
              Page {data.page} of {totalPages} ({data.total} payments)
            </span>
            <button className="btn-secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        </>
      )}
    </>
  );
}
