import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminRestaurants,
  type AdminApprovalStatus,
  type AdminRestaurantListResponse,
  type AdminRestaurantStatus,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

export default function Restaurants() {
  const { accessToken } = useSession();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<AdminRestaurantListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [status, setStatus] = useState<AdminRestaurantStatus | "">("");
  const [openFilter, setOpenFilter] = useState<"" | "true" | "false">("");
  // Phase 24 — deep-linked from a dashboard alert with ?approval_status=PENDING.
  const [approvalStatus, setApprovalStatus] = useState<AdminApprovalStatus | "">(
    () => (searchParams.get("approval_status") as AdminApprovalStatus | null) ?? "",
  );
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminRestaurants(accessToken, {
          search: search || undefined,
          status: status || undefined,
          is_open: openFilter === "" ? undefined : openFilter === "true",
          approval_status: approvalStatus || undefined,
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load restaurants.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, status, openFilter, approvalStatus, page]);

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
      <h2 className="section-title">Restaurants</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search name, phone, email…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="filter-input"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AdminRestaurantStatus | "");
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="INACTIVE">Inactive</option>
        </select>
        <select
          className="filter-input"
          value={openFilter}
          onChange={(e) => {
            setOpenFilter(e.target.value as "" | "true" | "false");
            setPage(1);
          }}
        >
          <option value="">Open or closed</option>
          <option value="true">Open</option>
          <option value="false">Closed</option>
        </select>
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
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No restaurants match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Restaurant</th>
                  <th>Owner</th>
                  <th>Status</th>
                  <th>Approval</th>
                  <th>Open</th>
                  <th>Rating</th>
                  <th>Orders</th>
                  <th>Revenue</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((restaurant) => (
                  <tr key={restaurant.id}>
                    <td>
                      <Link to={`/restaurants/${restaurant.id}`}>{restaurant.name}</Link>
                    </td>
                    <td className="muted">{restaurant.owner_name}</td>
                    <td>
                      <span className={`status-pill status-${restaurant.status.toLowerCase()}`}>{restaurant.status}</span>
                    </td>
                    <td>
                      <span className={`status-pill status-${restaurant.approval_status.toLowerCase()}`}>
                        {restaurant.approval_status}
                      </span>
                    </td>
                    <td className="muted">{restaurant.is_open ? "Open" : "Closed"}</td>
                    <td className="muted">{restaurant.average_rating}</td>
                    <td>{restaurant.order_count}</td>
                    <td>₹{restaurant.total_revenue}</td>
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
              Page {data.page} of {totalPages} ({data.total} restaurants)
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
