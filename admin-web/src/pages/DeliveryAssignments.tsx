import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminDeliveryAssignments,
  type AdminAssignmentStatusValue,
  type AdminDeliveryAssignmentListResponse,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

const STATUS_OPTIONS: AdminAssignmentStatusValue[] = [
  "PENDING",
  "ACCEPTED",
  "REJECTED",
  "ARRIVED_AT_RESTAURANT",
  "PICKED_UP",
  "OUT_FOR_DELIVERY",
  "DELIVERED",
  "CANCELLED",
];

export default function DeliveryAssignments() {
  const { accessToken } = useSession();
  const [data, setData] = useState<AdminDeliveryAssignmentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [status, setStatus] = useState<AdminAssignmentStatusValue | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminDeliveryAssignments(accessToken, {
          search: search || undefined,
          status: status || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load delivery assignments.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, status, dateFrom, dateTo, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <>
      <h2 className="section-title">Delivery assignments</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search order # or rider…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ minWidth: 220 }}
        />
        <select
          className="filter-input"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AdminAssignmentStatusValue | "");
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
        <div className="empty-state">No delivery assignments match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Rider</th>
                  <th>Status</th>
                  <th>Accepted</th>
                  <th>Picked up</th>
                  <th>Delivered</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <tr key={entry.id ?? `pending-${entry.order_id}`}>
                    <td>
                      {entry.id ? (
                        <Link to={`/delivery-assignments/${entry.id}`}>{entry.order_number}</Link>
                      ) : (
                        <Link to={`/orders/${entry.order_id}`}>{entry.order_number}</Link>
                      )}
                    </td>
                    <td className="muted">{entry.rider_name ?? "Unclaimed"}</td>
                    <td>
                      <span className={`status-pill status-${entry.status === "PENDING" ? "pending" : entry.status === "DELIVERED" ? "approved" : entry.status === "REJECTED" || entry.status === "CANCELLED" ? "rejected" : "pending"}`}>
                        {entry.status.replaceAll("_", " ")}
                      </span>
                    </td>
                    <td className="muted">{entry.accepted_at ? new Date(entry.accepted_at).toLocaleString() : "—"}</td>
                    <td className="muted">{entry.picked_up_at ? new Date(entry.picked_up_at).toLocaleString() : "—"}</td>
                    <td className="muted">{entry.delivered_at ? new Date(entry.delivered_at).toLocaleString() : "—"}</td>
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
              Page {data.page} of {totalPages} ({data.total} assignments)
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
