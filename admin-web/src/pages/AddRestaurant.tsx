import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useToast } from "@/components/toast/ToastProvider";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { createAdminRestaurant } from "@/services/api/adminApi";

type FormState = {
  owner_name: string;
  email: string;
  password: string;
  owner_phone: string;
  restaurant_name: string;
  description: string;
  restaurant_phone: string;
  address: string;
  latitude: string;
  longitude: string;
};

const EMPTY_FORM: FormState = {
  owner_name: "",
  email: "",
  password: "",
  owner_phone: "",
  restaurant_name: "",
  description: "",
  restaurant_phone: "",
  address: "",
  latitude: "",
  longitude: "",
};

/** Accepts "26.0486, 82.6847" — what Google Maps copies when you click a
 * place's coordinates — pasted into either coordinate box. */
function splitCoordinatePair(value: string): [string, string] | null {
  const match = value.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
  return match ? [match[1], match[2]] : null;
}

export default function AddRestaurant() {
  const { accessToken } = useSession();
  const navigate = useNavigate();
  const toast = useToast();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(false);

  function updateField(field: keyof FormState, value: string) {
    if (field === "latitude" || field === "longitude") {
      const pair = splitCoordinatePair(value);
      if (pair) {
        setForm((current) => ({ ...current, latitude: pair[0], longitude: pair[1] }));
        return;
      }
    }
    setForm((current) => ({ ...current, [field]: value }));
  }

  function fillCurrentLocation() {
    if (!navigator.geolocation) {
      setError("This browser can't share its location. Enter the coordinates manually.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setForm((current) => ({
          ...current,
          latitude: position.coords.latitude.toFixed(6),
          longitude: position.coords.longitude.toFixed(6),
        }));
        setLocating(false);
      },
      () => {
        setError("Couldn't get your location. Enter the coordinates manually.");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!accessToken) return;
    const latitude = Number(form.latitude);
    const longitude = Number(form.longitude);
    if (form.latitude.trim() === "" || form.longitude.trim() === "" || Number.isNaN(latitude) || Number.isNaN(longitude)) {
      setError("Enter the restaurant's latitude and longitude.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const restaurant = await createAdminRestaurant(accessToken, {
        owner_name: form.owner_name.trim(),
        email: form.email.trim(),
        password: form.password,
        owner_phone: form.owner_phone.trim() || null,
        restaurant_name: form.restaurant_name.trim(),
        description: form.description.trim() || null,
        restaurant_phone: form.restaurant_phone.trim(),
        address: form.address.trim(),
        latitude,
        longitude,
      });
      toast.success(`${restaurant.name} added. The owner can now log in with ${restaurant.owner_email}.`);
      navigate(`/restaurants/${restaurant.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to add restaurant.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Link to="/restaurants" className="back-link">
        ← Back to restaurants
      </Link>
      <h2 className="section-title">Add restaurant</h2>
      <p className="muted" style={{ marginTop: 0, marginBottom: 16, maxWidth: 760 }}>
        Creates the owner's login and their restaurant together. The restaurant goes live right away, and the owner
        signs in to the restaurant portal with the email and password you set here.
      </p>

      <form onSubmit={handleSubmit}>
        <section className="form-card">
          <h3>Owner login</h3>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="owner_name">Owner name</label>
              <input id="owner_name" required minLength={2} value={form.owner_name} onChange={(e) => updateField("owner_name", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="owner_phone">Owner phone (optional)</label>
              <input id="owner_phone" type="tel" value={form.owner_phone} onChange={(e) => updateField("owner_phone", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="email">Login email</label>
              <input id="email" type="email" required autoComplete="off" value={form.email} onChange={(e) => updateField("email", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="text"
                required
                minLength={8}
                autoComplete="new-password"
                value={form.password}
                onChange={(e) => updateField("password", e.target.value)}
              />
              <span className="hint">At least 8 characters. Share it with the owner securely.</span>
            </div>
          </div>
        </section>

        <section className="form-card">
          <h3>Restaurant</h3>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="restaurant_name">Restaurant name</label>
              <input id="restaurant_name" required minLength={2} value={form.restaurant_name} onChange={(e) => updateField("restaurant_name", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="restaurant_phone">Restaurant phone</label>
              <input id="restaurant_phone" type="tel" required value={form.restaurant_phone} onChange={(e) => updateField("restaurant_phone", e.target.value)} />
            </div>
            <div className="field span-2">
              <label htmlFor="address">Address</label>
              <input id="address" required minLength={5} value={form.address} onChange={(e) => updateField("address", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="latitude">Latitude</label>
              <input id="latitude" inputMode="decimal" required value={form.latitude} onChange={(e) => updateField("latitude", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="longitude">Longitude</label>
              <input id="longitude" inputMode="decimal" required value={form.longitude} onChange={(e) => updateField("longitude", e.target.value)} />
            </div>
            <div className="field span-2" style={{ marginTop: -6 }}>
              <button type="button" className="btn-secondary link-button" onClick={fillCurrentLocation} disabled={locating}>
                {locating ? "Locating…" : "Use my current location"}
              </button>
              <span className="hint">
                Or in Google Maps, right-click the restaurant, click the coordinates to copy them, and paste into either box.
              </span>
            </div>
            <div className="field span-2">
              <label htmlFor="description">Description (optional)</label>
              <textarea id="description" maxLength={5000} value={form.description} onChange={(e) => updateField("description", e.target.value)} />
            </div>
          </div>
        </section>

        {error && (
          <div className="error-banner" role="alert" style={{ maxWidth: 760 }}>
            {error}
          </div>
        )}

        <div className="form-actions">
          <button className="btn-primary" type="submit" disabled={saving}>
            {saving ? "Adding…" : "Add restaurant"}
          </button>
          <Link to="/restaurants" className="btn-secondary link-button">
            Cancel
          </Link>
        </div>
      </form>
    </>
  );
}
