import { Fragment, useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminCODReconciliation,
  getAdminCODReconciliationDetail,
  settleAdminCOD,
  type AdminCODReconciliationDetail,
  type AdminCODReconciliationListResponse,
  type AdminCODSettlementStatus,
} from "@/services/api/adminApi";

const PAGE_SIZE = 20;

function statusPillClass(status: AdminCODSettlementStatus) {
  if (status === "SETTLED") return "status-approved";
  if (status === "PARTIAL") return "status-pending";
  return "status-rejected";
}

export default function CODReconciliation() {
  const { accessToken } = useSession();
  const { promptText } = useConfirm();
  const toast = useToast();
  const [data, setData] = useState<AdminCODReconciliationListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningRiderId, setActioningRiderId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [status, setStatus] = useState<AdminCODSettlementStatus | "">("");
  const [page, setPage] = useState(1);

  const [expandedRiderId, setExpandedRiderId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<AdminCODReconciliationDetail | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminCODReconciliation(accessToken, {
          search: search || undefined,
          status: status || undefined,
          page,
          limit: PAGE_SIZE,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load COD reconciliation.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, status, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  async function toggleExpand(riderId: string) {
    if (!accessToken) return;
    if (expandedRiderId === riderId) {
      setExpandedRiderId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedRiderId(riderId);
    setExpandedDetail(null);
    setExpandedLoading(true);
    try {
      setExpandedDetail(await getAdminCODReconciliationDetail(accessToken, riderId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load settlement history.");
    } finally {
      setExpandedLoading(false);
    }
  }

  async function handleSettle(riderId: string, riderName: string, outstanding: string) {
    if (!accessToken) return;
    const amountInput = await promptText({
      title: "Record COD settlement",
      message: `Amount ${riderName} is remitting now (outstanding: ₹${outstanding}).`,
      label: "Amount",
      defaultValue: outstanding,
      required: true,
    });
    if (!amountInput || !amountInput.trim()) return;
    const note = await promptText({ title: "Settlement note", label: "Note (optional)" });

    setActioningRiderId(riderId);
    try {
      await settleAdminCOD(accessToken, riderId, amountInput.trim(), note?.trim() || undefined);
      toast.success(`Recorded ₹${amountInput.trim()} settlement for ${riderName}.`);
      await load();
      if (expandedRiderId === riderId) {
        setExpandedDetail(await getAdminCODReconciliationDetail(accessToken, riderId));
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to record settlement.");
    } finally {
      setActioningRiderId(null);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;

  return (
    <>
      <h2 className="section-title">COD reconciliation</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search rider…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="filter-input"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as AdminCODSettlementStatus | "");
            setPage(1);
          }}
        >
          <option value="">Any status</option>
          <option value="PENDING">Pending</option>
          <option value="PARTIAL">Partial</option>
          <option value="SETTLED">Settled</option>
        </select>
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No riders with COD activity match these filters.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Rider</th>
                  <th>COD collected</th>
                  <th>Expected settlement</th>
                  <th>Settled</th>
                  <th>Outstanding</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <Fragment key={row.rider_id}>
                    <tr>
                      <td>
                        <button
                          className="btn-secondary"
                          style={{ padding: "4px 10px" }}
                          onClick={() => toggleExpand(row.rider_id)}
                        >
                          {row.rider_name}
                        </button>
                      </td>
                      <td>₹{row.cod_collected}</td>
                      <td>₹{row.expected_settlement}</td>
                      <td>₹{row.settled_amount}</td>
                      <td>₹{row.outstanding_amount}</td>
                      <td>
                        <span className={`status-pill ${statusPillClass(row.status)}`}>{row.status}</span>
                      </td>
                      <td>
                        {row.status !== "SETTLED" && (
                          <button
                            className="btn-secondary"
                            onClick={() => handleSettle(row.rider_id, row.rider_name, row.outstanding_amount)}
                            disabled={actioningRiderId === row.rider_id}
                          >
                            Settle
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedRiderId === row.rider_id && (
                      <tr>
                        <td colSpan={7} style={{ background: "#fff8f2" }}>
                          {expandedLoading ? (
                            <p className="muted">Loading settlement history…</p>
                          ) : !expandedDetail || expandedDetail.settlements.length === 0 ? (
                            <p className="muted">No settlements recorded yet for this rider.</p>
                          ) : (
                            <div>
                              {expandedDetail.settlements.map((s) => (
                                <div key={s.id} style={{ padding: "6px 0" }}>
                                  <div className="muted">
                                    ₹{s.amount} — {new Date(s.created_at).toLocaleString()}
                                    {s.note ? ` — ${s.note}` : ""}
                                  </div>
                                  {/* Financial Ledger Validation (Phase 30) — exactly
                                      which collected orders this settlement covers,
                                      not just a lump-sum figure. */}
                                  {s.allocations.length > 0 && (
                                    <div style={{ paddingLeft: 16, fontSize: 12 }} className="muted">
                                      {s.allocations.map((a) => (
                                        <div key={a.cod_collection_id}>
                                          Order {a.order_number}: ₹{a.amount_allocated}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ))}
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
