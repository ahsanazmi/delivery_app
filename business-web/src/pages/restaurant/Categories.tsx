import { FormEvent, useCallback, useEffect, useState } from "react";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
    createCategory,
    deleteCategory,
    listCategories,
    updateCategory,
    type RestaurantCategory,
} from "@/services/api/categoriesApi";

type NewCategoryForm = {
  name: string;
  display_order: string;
  image_url: string;
};

const EMPTY_FORM: NewCategoryForm = { name: "", display_order: "0", image_url: "" };

export default function CategoriesPage() {
  const { accessToken } = useSession();
  const [categories, setCategories] = useState<RestaurantCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const [newCategory, setNewCategory] = useState<NewCategoryForm>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<NewCategoryForm>(EMPTY_FORM);
  const [savingEdit, setSavingEdit] = useState(false);

  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listCategories(accessToken);
      setCategories(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load categories.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !newCategory.name.trim()) return;

    setCreating(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const created = await createCategory(accessToken, {
        name: newCategory.name.trim(),
        display_order: Number(newCategory.display_order) || 0,
        image_url: newCategory.image_url.trim() || null,
      });
      setCategories((current) => [...current, created].sort((a, b) => a.display_order - b.display_order));
      setNewCategory(EMPTY_FORM);
      setSuccessMessage(`"${created.name}" added.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create category.");
    } finally {
      setCreating(false);
    }
  }

  function startEditing(category: RestaurantCategory) {
    setEditingId(category.id);
    setEditForm({
      name: category.name,
      display_order: String(category.display_order),
      image_url: category.image_url ?? "",
    });
    setError(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setEditForm(EMPTY_FORM);
  }

  async function handleSaveEdit(categoryId: string) {
    if (!accessToken || !editForm.name.trim()) return;
    setSavingEdit(true);
    setError(null);
    try {
      const updated = await updateCategory(accessToken, categoryId, {
        name: editForm.name.trim(),
        display_order: Number(editForm.display_order) || 0,
        image_url: editForm.image_url.trim() || null,
      });
      setCategories((current) =>
        current.map((c) => (c.id === categoryId ? updated : c)).sort((a, b) => a.display_order - b.display_order),
      );
      setEditingId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save changes.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleToggleActive(category: RestaurantCategory) {
    if (!accessToken) return;
    setBusyId(category.id);
    setError(null);
    try {
      const updated = await updateCategory(accessToken, category.id, { is_active: !category.is_active });
      setCategories((current) => current.map((c) => (c.id === category.id ? updated : c)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to update category.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(category: RestaurantCategory) {
    if (!accessToken) return;
    if (!window.confirm(`Delete "${category.name}"? Products in this category will become uncategorized.`)) return;

    setBusyId(category.id);
    setError(null);
    try {
      await deleteCategory(accessToken, category.id);
      setCategories((current) => current.filter((c) => c.id !== category.id));
      setSuccessMessage(`"${category.name}" deleted.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete category.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return <p className="page-center">Loading categories…</p>;
  }

  return (
    <div className="categories-page">
      <h2 className="section-title">Menu categories</h2>
      <p className="subtitle" style={{ marginBottom: 20 }}>
        Organize your menu into sections like Pizza, Burgers, or Desserts.
      </p>

      {successMessage && <div className="success-banner">{successMessage}</div>}
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <form onSubmit={handleCreate} className="profile-form" style={{ marginBottom: 24 }}>
        <div className="field-row">
          <div className="field">
            <label htmlFor="new-name">Category name</label>
            <input
              id="new-name"
              value={newCategory.name}
              onChange={(e) => setNewCategory((current) => ({ ...current, name: e.target.value }))}
              placeholder="e.g. Pizza"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="new-order">Display order</label>
            <input
              id="new-order"
              type="number"
              min="0"
              value={newCategory.display_order}
              onChange={(e) => setNewCategory((current) => ({ ...current, display_order: e.target.value }))}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="new-image">Image URL (optional)</label>
          <input
            id="new-image"
            type="url"
            value={newCategory.image_url}
            onChange={(e) => setNewCategory((current) => ({ ...current, image_url: e.target.value }))}
            placeholder="https://…"
          />
        </div>
        <div className="profile-form-actions">
          <button type="submit" className="btn-primary" style={{ width: "auto", padding: "0 24px" }} disabled={creating}>
            {creating ? "Adding…" : "Add category"}
          </button>
        </div>
      </form>

      {categories.length === 0 ? (
        <div className="empty-state">No categories yet — add your first one above.</div>
      ) : (
        <div className="category-list">
          {categories.map((category) => {
            const isEditing = editingId === category.id;
            const isBusy = busyId === category.id;
            return (
              <div className={`category-row ${category.is_active ? "" : "category-row-disabled"}`} key={category.id}>
                {category.image_url ? (
                  <img
                    src={category.image_url}
                    alt={category.name}
                    className="category-thumb"
                    onError={(e) => (e.currentTarget.style.visibility = "hidden")}
                  />
                ) : (
                  <div className="category-thumb category-thumb-placeholder">🍽️</div>
                )}

                {isEditing ? (
                  <div className="category-edit-form">
                    <input
                      value={editForm.name}
                      onChange={(e) => setEditForm((current) => ({ ...current, name: e.target.value }))}
                    />
                    <input
                      type="number"
                      min="0"
                      value={editForm.display_order}
                      onChange={(e) => setEditForm((current) => ({ ...current, display_order: e.target.value }))}
                      style={{ width: 70 }}
                    />
                    <input
                      type="url"
                      value={editForm.image_url}
                      placeholder="Image URL"
                      onChange={(e) => setEditForm((current) => ({ ...current, image_url: e.target.value }))}
                    />
                    <div className="category-row-actions">
                      <button className="btn-secondary" onClick={cancelEditing} disabled={savingEdit}>
                        Cancel
                      </button>
                      <button
                        className="btn-primary"
                        style={{ width: "auto", padding: "0 14px" }}
                        onClick={() => handleSaveEdit(category.id)}
                        disabled={savingEdit}
                      >
                        {savingEdit ? "Saving…" : "Save"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="category-info">
                      <div className="category-name">{category.name}</div>
                      <div className="muted">Order: {category.display_order}</div>
                    </div>
                    <span className={`status-pill ${category.is_active ? "status-delivered" : "status-cancelled"}`}>
                      {category.is_active ? "Enabled" : "Disabled"}
                    </span>
                    <div className="category-row-actions">
                      <button className="btn-secondary" onClick={() => handleToggleActive(category)} disabled={isBusy}>
                        {category.is_active ? "Disable" : "Enable"}
                      </button>
                      <button className="btn-secondary" onClick={() => startEditing(category)} disabled={isBusy}>
                        Edit
                      </button>
                      <button className="btn-secondary btn-danger" onClick={() => handleDelete(category)} disabled={isBusy}>
                        Delete
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
