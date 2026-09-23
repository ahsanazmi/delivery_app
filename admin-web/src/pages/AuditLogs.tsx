import { Fragment, useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminAuditLog,
  getAdminAuditLogs,
  type AdminAuditLogDetail,
  type AdminAuditLogListResponse,
} from "@/services/api/adminApi";

const PAGE_SIZE = 50;

export default function AuditLogs() {
  const { accessToken } = useSession();
  const [data, setData] = useState<AdminAuditLogListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [actionFilter, setActionFilter] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<AdminAuditLogDetail | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminAuditLogs(accessToken, {
          action: actionFilter || undefined,
          entity_type: entityTypeFilter || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load audit logs.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, actionFilter, entityTypeFilter, dateFrom, dateTo, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    void load();
  }

  async function toggleExpand(id: string) {
    if (!accessToken) return;
    if (expandedId === id) {
      setExpandedId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedId(id);
    setExpandedDetail(null);
    setExpandedLoading(true);
    try {
      setExpandedDetail(await getAdminAuditLog(accessToken, id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load audit log detail.");
    } finally {
      setExpandedLoading(false);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <>
      <h2 className="section-title">Audit logs</h2>
      <p className="muted" style={{ marginTop: -8, marginBottom: 20 }}>
        Every explicit administrative intervention — order cancellations, rider reassignments, COD settlements, and more as this log grows.
      </p>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applyFilters}>
        <input
          className="filter-input"
          type="text"
          placeholder="Action (e.g. order.cancel)"
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
        />
        <input
          className="filter-input"
          type="text"
          placeholder="Entity type (e.g. order)"
          value={entityTypeFilter}
          onChange={(e) => setEntityTypeFilter(e.target.value)}
        />
        <input className="filter-input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <input className="filter-input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <button className="btn-secondary" type="submit">
          Filter
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No audit log entries match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Admin</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Entity ID</th>
                  <th>Reason</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <Fragment key={entry.id}>
                    <tr>
                      <td>
                        <button
                          className="btn-secondary"
                          style={{ padding: "4px 10px" }}
                          onClick={() => toggleExpand(entry.id)}
                        >
                          {entry.admin_name ?? entry.admin_id}
                        </button>
                      </td>
                      <td className="muted">{entry.action}</td>
                      <td className="muted">{entry.entity_type}</td>
                      <td className="muted" style={{ fontFamily: "monospace", fontSize: 12 }}>
                        {entry.entity_id}
                      </td>
                      <td>{entry.reason}</td>
                      <td className="muted">{new Date(entry.created_at).toLocaleString()}</td>
                    </tr>
                    {expandedId === entry.id && (
                      <tr>
                        <td colSpan={6} style={{ background: "#fff8f2" }}>
                          {expandedLoading ? (
                            <p className="muted">Loading…</p>
                          ) : !expandedDetail ? (
                            <p className="muted">Unable to load detail.</p>
                          ) : (
                            <div className="muted" style={{ padding: "4px 0" }}>
                              <div>Previous value: {expandedDetail.old_value ?? "—"}</div>
                              <div>New value: {expandedDetail.new_value ?? "—"}</div>
                              <div>IP address: {expandedDetail.ip_address ?? "—"}</div>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination-bar">
            <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span className="muted">
              Page {data.page} of {totalPages} ({data.total} entries)
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
