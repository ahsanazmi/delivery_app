import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminRiders,
  type AdminApprovalStatus,
  type AdminRiderListResponse,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

export default function Riders() {
  const { accessToken } = useSession();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<AdminRiderListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  // Phase 24 — an operational alert on the dashboard can deep-link here
  // with e.g. ?approval_status=PENDING already applied.
  const [approvalStatus, setApprovalStatus] = useState<AdminApprovalStatus | "">(
    () => (searchParams.get("approval_status") as AdminApprovalStatus | null) ?? "",
  );
  const [onlineFilter, setOnlineFilter] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminRiders(accessToken, {
          search: search || undefined,
          approval_status: approvalStatus || undefined,
          is_online: onlineFilter === "" ? undefined : onlineFilter === "true",
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load riders.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, approvalStatus, onlineFilter, page]);

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
      <h2 className="section-title">Riders</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search name, email, phone…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="filter-input"
          value={approvalStatus}
          onChange={(e) => {
            setApprovalStatus(e.target.value as AdminApprovalStatus | "");
            setPage(1);
          }}
        >
          <option value="">Any approval</option>
          <option value="PENDING">Pending</option>
          <option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option>
          <option value="SUSPENDED">Suspended</option>
        </select>
        <select
          className="filter-input"
          value={onlineFilter}
          onChange={(e) => {
            setOnlineFilter(e.target.value as "" | "true" | "false");
            setPage(1);
          }}
        >
          <option value="">Online or offline</option>
          <option value="true">Online</option>
          <option value="false">Offline</option>
        </select>
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No riders match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Rider</th>
                  <th>Phone</th>
                  <th>Approval</th>
                  <th>Online</th>
                  <th>Vehicle</th>
                  <th>Rating</th>
                  <th>Deliveries</th>
                  <th>Earnings</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((rider) => (
                  <tr key={rider.id}>
                    <td>
                      <Link to={`/riders/${rider.id}`}>{rider.name}</Link>
                    </td>
                    <td className="muted">{rider.phone ?? "—"}</td>
                    <td>
                      <span className={`status-pill status-${rider.approval_status.toLowerCase()}`}>
                        {rider.approval_status}
                      </span>
                    </td>
                    <td className="muted">{rider.is_online ? "Online" : "Offline"}</td>
                    <td className="muted">{rider.vehicle_type ? `${rider.vehicle_type}${rider.vehicle_number ? ` · ${rider.vehicle_number}` : ""}` : "—"}</td>
                    <td className="muted">{rider.rating > 0 ? rider.rating.toFixed(2) : "—"}</td>
                    <td>{rider.deliveries_count}</td>
                    <td>₹{rider.total_earnings}</td>
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
              Page {data.page} of {totalPages} ({data.total} riders)
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
