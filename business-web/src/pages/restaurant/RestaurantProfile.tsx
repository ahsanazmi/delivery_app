import { FormEvent, useCallback, useEffect, useState } from "react";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
    getRestaurantProfile,
    updateRestaurantProfile,
    type RestaurantProfileUpdatePayload,
    type RestaurantSummary,
} from "@/services/api/restaurantApi";

type FormState = {
  name: string;
  description: string;
  phone: string;
  email: string;
  address: string;
  latitude: string;
  longitude: string;
  minimum_order: string;
  delivery_fee: string;
  logo_url: string;
  cover_image_url: string;
};

function toFormState(restaurant: RestaurantSummary): FormState {
  return {
    name: restaurant.name,
    description: restaurant.description ?? "",
    phone: restaurant.phone,
    email: restaurant.email ?? "",
    address: restaurant.address,
    latitude: String(restaurant.latitude),
    longitude: String(restaurant.longitude),
    minimum_order: String(restaurant.minimum_order),
    delivery_fee: String(restaurant.delivery_fee),
    logo_url: restaurant.logo_url ?? "",
    cover_image_url: restaurant.cover_image_url ?? "",
  };
}

export default function RestaurantProfilePage() {
  const { accessToken } = useSession();
  const [restaurant, setRestaurant] = useState<RestaurantSummary | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getRestaurantProfile(accessToken);
      setRestaurant(data);
      setForm(toFormState(data));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load your restaurant profile.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  function updateField<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((current) => (current ? { ...current, [field]: value } : current));
  }

  function cancelEditing() {
    if (restaurant) setForm(toFormState(restaurant));
    setEditing(false);
    setError(null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !form) return;

    setSaving(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const payload: RestaurantProfileUpdatePayload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        phone: form.phone.trim(),
        email: form.email.trim() || null,
        address: form.address.trim(),
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        minimum_order: Number(form.minimum_order),
        delivery_fee: Number(form.delivery_fee),
        logo_url: form.logo_url.trim() || null,
        cover_image_url: form.cover_image_url.trim() || null,
      };
      const updated = await updateRestaurantProfile(accessToken, payload);
      setRestaurant(updated);
      setForm(toFormState(updated));
      setEditing(false);
      setSuccessMessage("Restaurant profile updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save changes.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="page-center">Loading restaurant profile…</p>;
  }

  if (error && !restaurant) {
    return (
      <div className="error-banner" role="alert">
        {error}
        <button className="btn-secondary" style={{ marginLeft: 12 }} onClick={() => load()}>
          Try again
        </button>
      </div>
    );
  }

  if (!restaurant || !form) return null;

  return (
    <div className="restaurant-profile">
      {successMessage && <div className="success-banner">{successMessage}</div>}
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <div className="profile-cover">
        {form.cover_image_url ? (
          <img src={form.cover_image_url} alt="Cover" className="cover-image" onError={(e) => (e.currentTarget.style.display = "none")} />
        ) : (
          <div className="cover-image-placeholder">No cover image set</div>
        )}
        <div className="profile-logo-wrap">
          {form.logo_url ? (
            <img src={form.logo_url} alt="Logo" className="logo-image" onError={(e) => (e.currentTarget.style.display = "none")} />
          ) : (
            <div className="logo-image-placeholder">🍽️</div>
          )}
        </div>
      </div>

      <div className="profile-header-row">
        <h2 className="section-title" style={{ margin: 0 }}>
          {editing ? "Edit restaurant profile" : restaurant.name}
        </h2>
        {!editing && (
          <button className="btn-primary" style={{ width: "auto", padding: "0 20px" }} onClick={() => setEditing(true)}>
            Edit profile
          </button>
        )}
      </div>

      {!editing ? (
        <div className="profile-view-grid">
          <div className="profile-field">
            <div className="profile-field-label">Description</div>
            <div className="profile-field-value">{restaurant.description || "—"}</div>
          </div>
          <div className="profile-field">
            <div className="profile-field-label">Phone</div>
            <div className="profile-field-value">{restaurant.phone}</div>
          </div>
          <div className="profile-field">
            <div className="profile-field-label">Email</div>
            <div className="profile-field-value">{restaurant.email || "—"}</div>
          </div>
          <div className="profile-field">
            <div className="profile-field-label">Address</div>
            <div className="profile-field-value">{restaurant.address}</div>
          </div>
          <div className="profile-field">
            <div className="profile-field-label">Coordinates</div>
            <div className="profile-field-value">
              {restaurant.latitude}, {restaurant.longitude}
            </div>
          </div>
          <div className="profile-field">
            <div className="profile-field-label">Minimum order</div>
            <div className="profile-field-value">₹{Number(restaurant.minimum_order).toFixed(2)}</div>
          </div>
          <div className="profile-field">
            <div className="profile-field-label">Delivery fee</div>
            <div className="profile-field-value">₹{Number(restaurant.delivery_fee).toFixed(2)}</div>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="profile-form">
          <div className="field">
            <label htmlFor="name">Restaurant name</label>
            <input id="name" value={form.name} onChange={(e) => updateField("name", e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="description">Description</label>
            <textarea
              id="description"
              rows={3}
              value={form.description}
              onChange={(e) => updateField("description", e.target.value)}
            />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="phone">Phone</label>
              <input id="phone" value={form.phone} onChange={(e) => updateField("phone", e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => updateField("email", e.target.value)}
                placeholder="contact@yourrestaurant.com"
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="address">Address</label>
            <textarea id="address" rows={2} value={form.address} onChange={(e) => updateField("address", e.target.value)} required />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="latitude">Latitude</label>
              <input
                id="latitude"
                type="number"
                step="any"
                value={form.latitude}
                onChange={(e) => updateField("latitude", e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="longitude">Longitude</label>
              <input
                id="longitude"
                type="number"
                step="any"
                value={form.longitude}
                onChange={(e) => updateField("longitude", e.target.value)}
                required
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="minimum_order">Minimum order (₹)</label>
              <input
                id="minimum_order"
                type="number"
                step="0.01"
                min="0"
                value={form.minimum_order}
                onChange={(e) => updateField("minimum_order", e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="delivery_fee">Delivery fee (₹)</label>
              <input
                id="delivery_fee"
                type="number"
                step="0.01"
                min="0"
                value={form.delivery_fee}
                onChange={(e) => updateField("delivery_fee", e.target.value)}
                required
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="logo_url">Logo image URL</label>
            <input
              id="logo_url"
              type="url"
              value={form.logo_url}
              onChange={(e) => updateField("logo_url", e.target.value)}
              placeholder="https://…"
            />
          </div>
          <div className="field">
            <label htmlFor="cover_image_url">Cover image URL</label>
            <input
              id="cover_image_url"
              type="url"
              value={form.cover_image_url}
              onChange={(e) => updateField("cover_image_url", e.target.value)}
              placeholder="https://…"
            />
          </div>

          <div className="profile-form-actions">
            <button type="button" className="btn-secondary" onClick={cancelEditing} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" style={{ width: "auto", padding: "0 24px" }} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
