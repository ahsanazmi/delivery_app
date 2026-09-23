import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  createAdminCoupon,
  deleteAdminCoupon,
  getAdminCoupons,
  updateAdminCoupon,
  type AdminCoupon,
  type AdminCouponListResponse,
  type AdminDiscountType,
} from "@/services/api/adminApi";

type NewCouponForm = {
  code: string;
  discountType: AdminDiscountType;
  discountValue: string;
  minOrder: string;
  maxDiscount: string;
  endDate: string;
  usageLimit: string;
  perCustomerLimit: string;
};

const EMPTY_NEW_FORM: NewCouponForm = {
  code: "",
  discountType: "percent",
  discountValue: "",
  minOrder: "0",
  maxDiscount: "",
  endDate: "",
  usageLimit: "",
  perCustomerLimit: "1",
};

export default function Coupons() {
  const { accessToken } = useSession();
  const { confirm } = useConfirm();
  const toast = useToast();
  const [data, setData] = useState<AdminCouponListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningId, setActioningId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "true" | "false">("");

  const [newForm, setNewForm] = useState<NewCouponForm>(EMPTY_NEW_FORM);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminCoupons(accessToken, {
          search: search || undefined,
          is_active: statusFilter === "" ? undefined : statusFilter === "true",
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load coupons.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(searchInput.trim());
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!accessToken || !newForm.code.trim() || !newForm.discountValue.trim()) return;

    setCreating(true);
    try {
      await createAdminCoupon(accessToken, {
        code: newForm.code.trim(),
        discount_type: newForm.discountType,
        discount_value: newForm.discountValue.trim(),
        min_order: newForm.minOrder.trim() || "0",
        max_discount: newForm.maxDiscount.trim() || undefined,
        end_date: newForm.endDate ? new Date(newForm.endDate).toISOString() : undefined,
        usage_limit: newForm.usageLimit.trim() ? Number(newForm.usageLimit) : undefined,
        per_customer_limit: newForm.perCustomerLimit.trim() ? Number(newForm.perCustomerLimit) : undefined,
      });
      setNewForm(EMPTY_NEW_FORM);
      toast.success(`Coupon "${newForm.code.trim()}" created.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to create coupon.");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(coupon: AdminCoupon) {
    if (!accessToken) return;
    setActioningId(coupon.id);
    try {
      await updateAdminCoupon(accessToken, coupon.id, { is_active: !coupon.is_active });
      toast.success(`"${coupon.code}" ${coupon.is_active ? "deactivated" : "activated"}.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update coupon.");
    } finally {
      setActioningId(null);
    }
  }

  async function handleDelete(coupon: AdminCoupon) {
    if (!accessToken) return;
    if (coupon.redemption_count > 0) {
      toast.error(`Cannot delete "${coupon.code}" — it has been redeemed ${coupon.redemption_count} time(s). Deactivate it instead.`);
      return;
    }
    const ok = await confirm({ title: `Delete coupon "${coupon.code}"?`, message: "This cannot be undone.", confirmLabel: "Delete", danger: true });
    if (!ok) return;

    setActioningId(coupon.id);
    try {
      await deleteAdminCoupon(accessToken, coupon.id);
      toast.success(`Coupon "${coupon.code}" deleted.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to delete coupon.");
    } finally {
      setActioningId(null);
    }
  }

  return (
    <>
      <h2 className="section-title">Coupons &amp; promotions</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={handleCreate} style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Code</label>
          <input value={newForm.code} onChange={(e) => setNewForm({ ...newForm, code: e.target.value })} placeholder="e.g. WELCOME10" />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Type</label>
          <select value={newForm.discountType} onChange={(e) => setNewForm({ ...newForm, discountType: e.target.value as AdminDiscountType })}>
            <option value="percent">Percent</option>
            <option value="fixed">Fixed</option>
          </select>
        </div>
        <div className="field" style={{ marginBottom: 0, width: 100 }}>
          <label>Value</label>
          <input value={newForm.discountValue} onChange={(e) => setNewForm({ ...newForm, discountValue: e.target.value })} placeholder="10" />
        </div>
        <div className="field" style={{ marginBottom: 0, width: 110 }}>
          <label>Min order</label>
          <input value={newForm.minOrder} onChange={(e) => setNewForm({ ...newForm, minOrder: e.target.value })} />
        </div>
        <div className="field" style={{ marginBottom: 0, width: 110 }}>
          <label>Max discount</label>
          <input value={newForm.maxDiscount} onChange={(e) => setNewForm({ ...newForm, maxDiscount: e.target.value })} placeholder="Optional" />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>End date</label>
          <input type="date" value={newForm.endDate} onChange={(e) => setNewForm({ ...newForm, endDate: e.target.value })} />
        </div>
        <div className="field" style={{ marginBottom: 0, width: 100 }}>
          <label>Usage limit</label>
          <input value={newForm.usageLimit} onChange={(e) => setNewForm({ ...newForm, usageLimit: e.target.value })} placeholder="Optional" />
        </div>
        <div className="field" style={{ marginBottom: 0, width: 100 }}>
          <label>Per customer</label>
          <input value={newForm.perCustomerLimit} onChange={(e) => setNewForm({ ...newForm, perCustomerLimit: e.target.value })} />
        </div>
        <button className="btn-secondary" type="submit" disabled={creating || !newForm.code.trim() || !newForm.discountValue.trim()}>
          Add coupon
        </button>
      </form>

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search code…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select className="filter-input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "" | "true" | "false")}>
          <option value="">Any status</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">No coupons yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Discount</th>
                <th>Min order</th>
                <th>Restaurant</th>
                <th>Ends</th>
                <th>Used</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((coupon) => (
                  <tr key={coupon.id}>
                    <td>{coupon.code}</td>
                    <td className="muted">
                      {coupon.discount_type === "percent" ? `${coupon.discount_value}%` : `₹${coupon.discount_value}`}
                      {coupon.max_discount ? ` (max ₹${coupon.max_discount})` : ""}
                    </td>
                    <td className="muted">₹{coupon.min_order}</td>
                    <td className="muted">{coupon.restaurant_name ?? "Any restaurant"}</td>
                    <td className="muted">{coupon.end_date ? new Date(coupon.end_date).toLocaleDateString() : "No expiry"}</td>
                    <td className="muted">
                      {coupon.redemption_count}
                      {coupon.usage_limit ? ` / ${coupon.usage_limit}` : ""}
                    </td>
                    <td>
                      <span className={`status-pill ${coupon.is_active ? "status-active" : "status-inactive"}`}>
                        {coupon.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn-secondary" onClick={() => handleToggleActive(coupon)} disabled={actioningId === coupon.id}>
                          {coupon.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button className="btn-secondary" onClick={() => handleDelete(coupon)} disabled={actioningId === coupon.id}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
