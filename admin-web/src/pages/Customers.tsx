import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminCustomers,
  type AdminCustomerListResponse,
  type AdminCustomerStatus,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

export default function Customers() {
  const { accessToken } = useSession();
  const [data, setData] = useState<AdminCustomerListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [status, setStatus] = useState<AdminCustomerStatus | "">("");
  const [registeredAfter, setRegisteredAfter] = useState("");
  const [registeredBefore, setRegisteredBefore] = useState("");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminCustomers(accessToken, {
          search: search || undefined,
          status: status || undefined,
          registered_after: registeredAfter || undefined,
          registered_before: registeredBefore || undefined,
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load customers.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, status, registeredAfter, registeredBefore, page]);

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
      <h2 className="section-title">Customers</h2>

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
            setStatus(e.target.value as AdminCustomerStatus | "");
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="ACTIVE">Active</option>
          <option value="SUSPENDED">Suspended</option>
        </select>
        <label className="filter-date-label">
          From
          <input
            className="filter-input"
            type="date"
            value={registeredAfter}
            onChange={(e) => {
              setRegisteredAfter(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <label className="filter-date-label">
          To
          <input
            className="filter-input"
            type="date"
            value={registeredBefore}
            onChange={(e) => {
              setRegisteredBefore(e.target.value);
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
        <div className="empty-state">No customers match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Contact</th>
                  <th>Status</th>
                  <th>Registered</th>
                  <th>Orders</th>
                  <th>Total spending</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((customer) => (
                  <tr key={customer.id}>
                    <td>
                      <Link to={`/customers/${customer.id}`}>{customer.name}</Link>
                    </td>
                    <td>
                      <div className="muted">{customer.email ?? "—"}</div>
                      <div className="muted">{customer.phone ?? "—"}</div>
                    </td>
                    <td>
                      <span className={`status-pill status-${customer.status.toLowerCase()}`}>{customer.status}</span>
                    </td>
                    <td className="muted">{new Date(customer.created_at).toLocaleDateString()}</td>
                    <td>{customer.order_count}</td>
                    <td>₹{customer.total_spending}</td>
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
              Page {data.page} of {totalPages} ({data.total} customers)
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
