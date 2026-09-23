import { FormEvent, useCallback, useEffect, useState } from "react";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { listCategories, type RestaurantCategory } from "@/services/api/categoriesApi";
import {
    createProduct,
    deleteProduct,
    listProducts,
    updateProduct,
    type ProductCreatePayload,
    type RestaurantProduct,
} from "@/services/api/productsApi";
import { rupees } from "@/utils/currency";

type ProductForm = {
  name: string;
  description: string;
  category_id: string;
  price: string;
  image_url: string;
};

const EMPTY_FORM: ProductForm = { name: "", description: "", category_id: "", price: "", image_url: "" };

function toPayload(form: ProductForm): ProductCreatePayload {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    category_id: form.category_id || null,
    price: Number(form.price),
    image_url: form.image_url.trim() || null,
  };
}

export default function ProductsPage() {
  const { accessToken } = useSession();
  const [products, setProducts] = useState<RestaurantProduct[]>([]);
  const [categories, setCategories] = useState<RestaurantCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const [newProduct, setNewProduct] = useState<ProductForm>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<ProductForm>(EMPTY_FORM);
  const [savingEdit, setSavingEdit] = useState(false);

  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const [productsData, categoriesData] = await Promise.all([
        listProducts(accessToken),
        listCategories(accessToken),
      ]);
      setProducts(productsData);
      setCategories(categoriesData);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load products.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  function categoryName(categoryId: string | null): string {
    if (!categoryId) return "Uncategorized";
    return categories.find((c) => c.id === categoryId)?.name ?? "Uncategorized";
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !newProduct.name.trim() || !newProduct.price) return;

    setCreating(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const created = await createProduct(accessToken, toPayload(newProduct));
      setProducts((current) => [...current, created]);
      setNewProduct(EMPTY_FORM);
      setSuccessMessage(`"${created.name}" added.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create product.");
    } finally {
      setCreating(false);
    }
  }

  function startEditing(product: RestaurantProduct) {
    setEditingId(product.id);
    setEditForm({
      name: product.name,
      description: product.description ?? "",
      category_id: product.category_id ?? "",
      price: String(product.price),
      image_url: product.image_url ?? "",
    });
    setError(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setEditForm(EMPTY_FORM);
  }

  async function handleSaveEdit(productId: string) {
    if (!accessToken || !editForm.name.trim() || !editForm.price) return;
    setSavingEdit(true);
    setError(null);
    try {
      const updated = await updateProduct(accessToken, productId, toPayload(editForm));
      setProducts((current) => current.map((p) => (p.id === productId ? updated : p)));
      setEditingId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save changes.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleToggleAvailability(product: RestaurantProduct) {
    if (!accessToken) return;
    setBusyId(product.id);
    setError(null);
    try {
      const updated = await updateProduct(accessToken, product.id, { is_available: !product.is_available });
      setProducts((current) => current.map((p) => (p.id === product.id ? updated : p)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to update product.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(product: RestaurantProduct) {
    if (!accessToken) return;
    if (!window.confirm(`Delete "${product.name}"? This can't be undone.`)) return;

    setBusyId(product.id);
    setError(null);
    try {
      await deleteProduct(accessToken, product.id);
      setProducts((current) => current.filter((p) => p.id !== product.id));
      setSuccessMessage(`"${product.name}" deleted.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete product.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return <p className="page-center">Loading products…</p>;
  }

  return (
    <div className="products-page">
      <h2 className="section-title">Menu products</h2>
      <p className="subtitle" style={{ marginBottom: 20 }}>
        Add, edit, and manage the dishes customers can order.
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
            <label htmlFor="new-product-name">Product name</label>
            <input
              id="new-product-name"
              value={newProduct.name}
              onChange={(e) => setNewProduct((current) => ({ ...current, name: e.target.value }))}
              placeholder="e.g. Butter Chicken"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="new-product-price">Price (₹)</label>
            <input
              id="new-product-price"
              type="number"
              step="0.01"
              min="0.01"
              value={newProduct.price}
              onChange={(e) => setNewProduct((current) => ({ ...current, price: e.target.value }))}
              required
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="new-product-description">Description</label>
          <textarea
            id="new-product-description"
            rows={2}
            value={newProduct.description}
            onChange={(e) => setNewProduct((current) => ({ ...current, description: e.target.value }))}
          />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="new-product-category">Category</label>
            <select
              id="new-product-category"
              value={newProduct.category_id}
              onChange={(e) => setNewProduct((current) => ({ ...current, category_id: e.target.value }))}
            >
              <option value="">Uncategorized</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="new-product-image">Image URL</label>
            <input
              id="new-product-image"
              type="url"
              value={newProduct.image_url}
              onChange={(e) => setNewProduct((current) => ({ ...current, image_url: e.target.value }))}
              placeholder="https://…"
            />
          </div>
        </div>
        <div className="profile-form-actions">
          <button type="submit" className="btn-primary" style={{ width: "auto", padding: "0 24px" }} disabled={creating}>
            {creating ? "Adding…" : "Add product"}
          </button>
        </div>
      </form>

      {products.length === 0 ? (
        <div className="empty-state">No products yet — add your first one above.</div>
      ) : (
        <div className="category-list">
          {products.map((product) => {
            const isEditing = editingId === product.id;
            const isBusy = busyId === product.id;
            return (
              <div className={`category-row ${product.is_available ? "" : "category-row-disabled"}`} key={product.id}>
                {product.image_url ? (
                  <img
                    src={product.image_url}
                    alt={product.name}
                    className="category-thumb"
                    onError={(e) => (e.currentTarget.style.visibility = "hidden")}
                  />
                ) : (
                  <div className="category-thumb category-thumb-placeholder">🍲</div>
                )}

                {isEditing ? (
                  <div className="category-edit-form" style={{ flexWrap: "wrap" }}>
                    <input
                      value={editForm.name}
                      onChange={(e) => setEditForm((current) => ({ ...current, name: e.target.value }))}
                      placeholder="Name"
                    />
                    <input
                      type="number"
                      step="0.01"
                      min="0.01"
                      value={editForm.price}
                      onChange={(e) => setEditForm((current) => ({ ...current, price: e.target.value }))}
                      style={{ width: 90 }}
                    />
                    <select
                      value={editForm.category_id}
                      onChange={(e) => setEditForm((current) => ({ ...current, category_id: e.target.value }))}
                    >
                      <option value="">Uncategorized</option>
                      {categories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                    <input
                      type="url"
                      value={editForm.image_url}
                      placeholder="Image URL"
                      onChange={(e) => setEditForm((current) => ({ ...current, image_url: e.target.value }))}
                    />
                    <textarea
                      rows={1}
                      value={editForm.description}
                      placeholder="Description"
                      onChange={(e) => setEditForm((current) => ({ ...current, description: e.target.value }))}
                      style={{ flexBasis: "100%" }}
                    />
                    <div className="category-row-actions">
                      <button className="btn-secondary" onClick={cancelEditing} disabled={savingEdit}>
                        Cancel
                      </button>
                      <button
                        className="btn-primary"
                        style={{ width: "auto", padding: "0 14px" }}
                        onClick={() => handleSaveEdit(product.id)}
                        disabled={savingEdit}
                      >
                        {savingEdit ? "Saving…" : "Save"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="category-info">
                      <div className="category-name">{product.name}</div>
                      <div className="muted">
                        {rupees(product.price)} · {categoryName(product.category_id)}
                      </div>
                      {product.description && <div className="muted">{product.description}</div>}
                    </div>
                    <span className={`status-pill ${product.is_available ? "status-delivered" : "status-cancelled"}`}>
                      {product.is_available ? "Available" : "Unavailable"}
                    </span>
                    <div className="category-row-actions">
                      <button className="btn-secondary" onClick={() => handleToggleAvailability(product)} disabled={isBusy}>
                        {product.is_available ? "Mark unavailable" : "Mark available"}
                      </button>
                      <button className="btn-secondary" onClick={() => startEditing(product)} disabled={isBusy}>
                        Edit
                      </button>
                      <button className="btn-secondary btn-danger" onClick={() => handleDelete(product)} disabled={isBusy}>
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
