import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminOrders,
  type AdminOrderListResponse,
  type AdminOrderStatus,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

const STATUS_OPTIONS: AdminOrderStatus[] = [
  "placed",
  "confirmed",
  "preparing",
  "ready_for_pickup",
  "rider_assigned",
  "picked_up",
  "out_for_delivery",
  "delivered",
  "cancelled",
  "rejected",
];

export default function Orders() {
  const { accessToken } = useSession();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<AdminOrderListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  // Phase 24 — deep-linked from a dashboard alert with ?status=cancelled
  // (or ?status=placed for the stale-unaccepted alert).
  const [status, setStatus] = useState<AdminOrderStatus | "">(
    () => (searchParams.get("status") as AdminOrderStatus | null) ?? "",
  );
  const [paymentMethod, setPaymentMethod] = useState("");
  const [paymentStatus, setPaymentStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(
    async (isPoll = false) => {
      if (!accessToken) return;
      if (!isPoll) setLoading(true);
      setError(null);
      try {
        setData(
          await getAdminOrders(accessToken, {
            search: search || undefined,
            status: status || undefined,
            payment_method: paymentMethod || undefined,
            payment_status: paymentStatus || undefined,
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
            page,
            limit: PAGE_SIZE,
          }),
        );
      } catch (err) {
        // A background poll failing silently is preferable to replacing a
        // working list with an error banner over a transient blip.
        if (!isPoll) setError(err instanceof ApiError ? err.message : "Unable to load orders.");
      } finally {
        if (!isPoll) setLoading(false);
      }
    },
    [accessToken, search, status, paymentMethod, paymentStatus, dateFrom, dateTo, page],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Frontend State Synchronization (Phase 19) — plain interval polling (no
  // WebSocket, no TanStack Query in this app yet), matching this phase's
  // own "polling is acceptable for MVP validation" guidance, so admin sees
  // a restaurant/rider-driven status change without a manual reload.
  useEffect(() => {
    const interval = setInterval(() => {
      void load(true);
    }, 15000);
    return () => clearInterval(interval);
  }, [load]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <>
      <h2 className="section-title">Orders</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search order #, customer, restaurant, rider…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select
          className="filter-input"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AdminOrderStatus | "");
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
        <input
          className="filter-input"
          type="text"
          placeholder="Payment method"
          value={paymentMethod}
          onChange={(e) => {
            setPaymentMethod(e.target.value);
            setPage(1);
          }}
          style={{ width: 140 }}
        />
        <input
          className="filter-input"
          type="text"
          placeholder="Payment status"
          value={paymentStatus}
          onChange={(e) => {
            setPaymentStatus(e.target.value);
            setPage(1);
          }}
          style={{ width: 140 }}
        />
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
        <div className="empty-state">No orders match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Customer</th>
                  <th>Restaurant</th>
                  <th>Rider</th>
                  <th>Status</th>
                  <th>Payment</th>
                  <th>Total</th>
                  <th>Placed</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((order) => (
                  <tr key={order.id}>
                    <td>
                      <Link to={`/orders/${order.id}`}>{order.order_number}</Link>
                    </td>
                    <td className="muted">{order.customer_name}</td>
                    <td className="muted">{order.restaurant_name ?? "—"}</td>
                    <td className="muted">{order.rider_name ?? "—"}</td>
                    <td className="muted">{order.status.replaceAll("_", " ")}</td>
                    <td className="muted">
                      {order.payment_method} · {order.payment_status}
                    </td>
                    <td>₹{order.total}</td>
                    <td className="muted">{new Date(order.created_at).toLocaleDateString()}</td>
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
              Page {data.page} of {totalPages} ({data.total} orders)
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
