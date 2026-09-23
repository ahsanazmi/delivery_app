import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminRestaurantOwners,
  type AdminRestaurantOwnerListResponse,
  type AdminRestaurantOwnerStatus,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

export default function RestaurantOwners() {
  const { accessToken } = useSession();
  const [data, setData] = useState<AdminRestaurantOwnerListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [status, setStatus] = useState<AdminRestaurantOwnerStatus | "">("");
  const [hasRestaurant, setHasRestaurant] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminRestaurantOwners(accessToken, {
          search: search || undefined,
          status: status || undefined,
          has_restaurant: hasRestaurant === "" ? undefined : hasRestaurant === "true",
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load restaurant owners.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, status, hasRestaurant, page]);

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
      <h2 className="section-title">Restaurant owners</h2>

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
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AdminRestaurantOwnerStatus | "");
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="SUSPENDED">Suspended</option>
        </select>
        <select
          className="filter-input"
          value={hasRestaurant}
          onChange={(e) => {
            setHasRestaurant(e.target.value as "" | "true" | "false");
            setPage(1);
          }}
        >
          <option value="">Any restaurant association</option>
          <option value="true">Has a restaurant</option>
          <option value="false">No restaurant yet</option>
        </select>
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No restaurant owners match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Owner</th>
                  <th>Contact</th>
                  <th>Restaurant</th>
                  <th>Status</th>
                  <th>Registered</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((owner) => (
                  <tr key={owner.id}>
                    <td>
                      <Link to={`/restaurant-owners/${owner.id}`}>{owner.name}</Link>
                    </td>
                    <td>
                      <div className="muted">{owner.email ?? "—"}</div>
                      <div className="muted">{owner.phone ?? "—"}</div>
                    </td>
                    <td className="muted">
                      {owner.restaurants.length === 0
                        ? "No restaurant"
                        : owner.restaurants.map((r) => r.name).join(", ")}
                    </td>
                    <td>
                      <span className={`status-pill status-${owner.status.toLowerCase()}`}>{owner.status}</span>
                    </td>
                    <td className="muted">{new Date(owner.created_at).toLocaleDateString()}</td>
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
              Page {data.page} of {totalPages} ({data.total} owners)
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
