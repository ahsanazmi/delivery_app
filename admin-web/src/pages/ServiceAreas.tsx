import { Fragment, useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  createAdminServiceArea,
  deleteAdminServiceArea,
  getAdminServiceAreas,
  updateAdminServiceArea,
  type AdminServiceArea,
  type AdminServiceAreaListResponse,
} from "@/services/api/adminApi";

function parsePostalCodes(raw: string): string[] {
  return Array.from(new Set(raw.split(",").map((code) => code.trim()).filter(Boolean)));
}

type EditForm = {
  city: string;
  district: string;
  zoneName: string;
  postalCodes: string;
  isActive: boolean;
};

function toEditForm(area: AdminServiceArea): EditForm {
  return {
    city: area.city,
    district: area.district ?? "",
    zoneName: area.zone_name,
    postalCodes: area.postal_codes.join(", "),
    isActive: area.is_active,
  };
}

export default function ServiceAreas() {
  const { accessToken } = useSession();
  const { confirm } = useConfirm();
  const toast = useToast();
  const [data, setData] = useState<AdminServiceAreaListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningId, setActioningId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "true" | "false">("");

  const [newCity, setNewCity] = useState("");
  const [newDistrict, setNewDistrict] = useState("");
  const [newZoneName, setNewZoneName] = useState("");
  const [newPostalCodes, setNewPostalCodes] = useState("");
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<EditForm | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(
        await getAdminServiceAreas(accessToken, {
          search: search || undefined,
          is_active: statusFilter === "" ? undefined : statusFilter === "true",
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load service areas.");
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
    if (!accessToken || !newCity.trim() || !newZoneName.trim()) return;
    const postalCodes = parsePostalCodes(newPostalCodes);
    if (postalCodes.length === 0) {
      toast.error("Add at least one postal code.");
      return;
    }

    setCreating(true);
    try {
      await createAdminServiceArea(accessToken, {
        city: newCity.trim(),
        district: newDistrict.trim() || undefined,
        zone_name: newZoneName.trim(),
        postal_codes: postalCodes,
      });
      setNewCity("");
      setNewDistrict("");
      setNewZoneName("");
      setNewPostalCodes("");
      toast.success(`Service area "${newZoneName.trim()}" created.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to create service area.");
    } finally {
      setCreating(false);
    }
  }

  function startEdit(area: AdminServiceArea) {
    setEditingId(area.id);
    setEditForm(toEditForm(area));
  }

  function cancelEdit() {
    setEditingId(null);
    setEditForm(null);
  }

  async function handleSaveEdit(areaId: string) {
    if (!accessToken || !editForm) return;
    const postalCodes = parsePostalCodes(editForm.postalCodes);
    if (postalCodes.length === 0) {
      toast.error("Add at least one postal code.");
      return;
    }

    setSaving(true);
    try {
      await updateAdminServiceArea(accessToken, areaId, {
        city: editForm.city.trim(),
        district: editForm.district.trim(),
        zone_name: editForm.zoneName.trim(),
        postal_codes: postalCodes,
        is_active: editForm.isActive,
      });
      cancelEdit();
      toast.success("Service area updated.");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update service area.");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleActive(area: AdminServiceArea) {
    if (!accessToken) return;
    setActioningId(area.id);
    try {
      await updateAdminServiceArea(accessToken, area.id, { is_active: !area.is_active });
      toast.success(`"${area.zone_name}" ${area.is_active ? "deactivated" : "activated"}.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update service area.");
    } finally {
      setActioningId(null);
    }
  }

  async function handleDelete(area: AdminServiceArea) {
    if (!accessToken) return;
    const ok = await confirm({ title: `Delete "${area.zone_name}" (${area.city})?`, message: "This cannot be undone.", confirmLabel: "Delete", danger: true });
    if (!ok) return;

    setActioningId(area.id);
    try {
      await deleteAdminServiceArea(accessToken, area.id);
      toast.success(`"${area.zone_name}" deleted.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to delete service area.");
    } finally {
      setActioningId(null);
    }
  }

  return (
    <>
      <h2 className="section-title">Service areas</h2>
      <p className="muted" style={{ marginTop: -8, marginBottom: 20 }}>
        Delivery zones the platform currently serves. Customer checkout is blocked for addresses outside every active
        zone once at least one zone exists.
      </p>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={handleCreate} style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>City</label>
          <input value={newCity} onChange={(e) => setNewCity(e.target.value)} placeholder="e.g. Karachi" />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>District</label>
          <input value={newDistrict} onChange={(e) => setNewDistrict(e.target.value)} placeholder="Optional" />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Zone name</label>
          <input value={newZoneName} onChange={(e) => setNewZoneName(e.target.value)} placeholder="e.g. DHA Phase 5" />
        </div>
        <div className="field" style={{ marginBottom: 0, minWidth: 220 }}>
          <label>Postal codes (comma-separated)</label>
          <input value={newPostalCodes} onChange={(e) => setNewPostalCodes(e.target.value)} placeholder="e.g. 75500, 75600" />
        </div>
        <button className="btn-secondary" type="submit" disabled={creating || !newCity.trim() || !newZoneName.trim()}>
          Add zone
        </button>
      </form>

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search city or zone…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="filter-input"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as "" | "true" | "false")}
        >
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
        <div className="empty-state">No service areas configured yet.</div>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>City</th>
                <th>District</th>
                <th>Zone</th>
                <th>Postal codes</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((area) => (
                <Fragment key={area.id}>
                  {editingId === area.id && editForm ? (
                    <tr>
                      <td colSpan={6}>
                        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", padding: "8px 0" }}>
                          <div className="field" style={{ marginBottom: 0 }}>
                            <label>City</label>
                            <input value={editForm.city} onChange={(e) => setEditForm({ ...editForm, city: e.target.value })} />
                          </div>
                          <div className="field" style={{ marginBottom: 0 }}>
                            <label>District</label>
                            <input
                              value={editForm.district}
                              onChange={(e) => setEditForm({ ...editForm, district: e.target.value })}
                            />
                          </div>
                          <div className="field" style={{ marginBottom: 0 }}>
                            <label>Zone name</label>
                            <input
                              value={editForm.zoneName}
                              onChange={(e) => setEditForm({ ...editForm, zoneName: e.target.value })}
                            />
                          </div>
                          <div className="field" style={{ marginBottom: 0, minWidth: 220 }}>
                            <label>Postal codes (comma-separated)</label>
                            <input
                              value={editForm.postalCodes}
                              onChange={(e) => setEditForm({ ...editForm, postalCodes: e.target.value })}
                            />
                          </div>
                          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <input
                              type="checkbox"
                              checked={editForm.isActive}
                              onChange={(e) => setEditForm({ ...editForm, isActive: e.target.checked })}
                            />
                            Active
                          </label>
                          <button className="btn-secondary" disabled={saving} onClick={() => handleSaveEdit(area.id)}>
                            Save
                          </button>
                          <button className="btn-secondary" disabled={saving} onClick={cancelEdit}>
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    <tr>
                      <td>{area.city}</td>
                      <td className="muted">{area.district || "—"}</td>
                      <td>{area.zone_name}</td>
                      <td className="muted">{area.postal_codes.join(", ")}</td>
                      <td>
                        <span className={`status-pill ${area.is_active ? "status-active" : "status-inactive"}`}>
                          {area.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button className="btn-secondary" onClick={() => startEdit(area)} disabled={actioningId === area.id}>
                            Edit
                          </button>
                          <button
                            className="btn-secondary"
                            onClick={() => handleToggleActive(area)}
                            disabled={actioningId === area.id}
                          >
                            {area.is_active ? "Deactivate" : "Activate"}
                          </button>
                          <button className="btn-secondary" onClick={() => handleDelete(area)} disabled={actioningId === area.id}>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
