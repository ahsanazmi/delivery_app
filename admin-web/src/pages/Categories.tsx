import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useToast } from "@/components/toast/ToastProvider";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  createAdminCategory,
  deleteAdminCategory,
  getAdminCategories,
  updateAdminCategory,
  type AdminCategory,
  type AdminCategoryListResponse,
} from "@/services/api/adminApi";

export default function Categories() {
  const { accessToken } = useSession();
  const { confirm, promptText } = useConfirm();
  const toast = useToast();
  const [data, setData] = useState<AdminCategoryListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actioningId, setActioningId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const [newName, setNewName] = useState("");
  const [newDisplayOrder, setNewDisplayOrder] = useState("0");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getAdminCategories(accessToken, { search: search || undefined }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load categories.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, search]);

  useEffect(() => {
    void load();
  }, [load]);

  function applySearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(searchInput.trim());
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!accessToken || !newName.trim()) return;
    setCreating(true);
    try {
      await createAdminCategory(accessToken, {
        name: newName.trim(),
        display_order: Number(newDisplayOrder) || 0,
      });
      setNewName("");
      setNewDisplayOrder("0");
      toast.success(`Category "${newName.trim()}" created.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to create category.");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(category: AdminCategory) {
    if (!accessToken) return;
    setActioningId(category.id);
    try {
      await updateAdminCategory(accessToken, category.id, { is_active: !category.is_active });
      toast.success(`"${category.name}" ${category.is_active ? "deactivated" : "activated"}.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to update category.");
    } finally {
      setActioningId(null);
    }
  }

  async function handleRename(category: AdminCategory) {
    if (!accessToken) return;
    const name = await promptText({ title: "Rename category", label: "New name", defaultValue: category.name, required: true });
    if (!name || !name.trim() || name.trim() === category.name) return;
    setActioningId(category.id);
    try {
      await updateAdminCategory(accessToken, category.id, { name: name.trim() });
      toast.success("Category renamed.");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to rename category.");
    } finally {
      setActioningId(null);
    }
  }

  async function handleDelete(category: AdminCategory) {
    if (!accessToken) return;
    if (category.restaurant_count > 0) {
      toast.error(
        `Cannot delete "${category.name}" — ${category.restaurant_count} restaurant(s) still use it. Deactivate it instead, or reassign those restaurants first.`,
      );
      return;
    }
    const ok = await confirm({ title: `Delete "${category.name}"?`, message: "This cannot be undone.", confirmLabel: "Delete", danger: true });
    if (!ok) return;

    setActioningId(category.id);
    try {
      await deleteAdminCategory(accessToken, category.id);
      toast.success(`"${category.name}" deleted.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Unable to delete category.");
    } finally {
      setActioningId(null);
    }
  }

  return (
    <>
      <h2 className="section-title">Categories</h2>
      <p className="muted" style={{ marginTop: -8, marginBottom: 20 }}>
        Platform-wide cuisine categories shown on the customer home page — separate from each restaurant's own menu sections.
      </p>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={handleCreate} style={{ alignItems: "flex-end" }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>New category name</label>
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Italian" />
        </div>
        <div className="field" style={{ marginBottom: 0, width: 100 }}>
          <label>Order</label>
          <input type="number" value={newDisplayOrder} onChange={(e) => setNewDisplayOrder(e.target.value)} />
        </div>
        <button className="btn-secondary" type="submit" disabled={creating || !newName.trim()}>
          Add category
        </button>
      </form>

      <form className="filter-bar" onSubmit={applySearch}>
        <input
          className="filter-input"
          type="text"
          placeholder="Search categories…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <button className="btn-secondary" type="submit">
          Search
        </button>
      </form>

      {loading ? (
        <LoadingIndicator />
      ) : !data || data.items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">▤</div>
          No categories yet.
        </div>
      ) : (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Order</th>
                <th>Status</th>
                <th>Restaurants using it</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((category) => (
                <tr key={category.id}>
                  <td>{category.name}</td>
                  <td className="muted">{category.display_order}</td>
                  <td>
                    <span className={`status-pill ${category.is_active ? "status-active" : "status-inactive"}`}>
                      {category.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="muted">{category.restaurant_count}</td>
                  <td>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button className="btn-secondary" onClick={() => handleRename(category)} disabled={actioningId === category.id}>
                        Rename
                      </button>
                      <button className="btn-secondary" onClick={() => handleToggleActive(category)} disabled={actioningId === category.id}>
                        {category.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button className="btn-secondary" onClick={() => handleDelete(category)} disabled={actioningId === category.id}>
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
