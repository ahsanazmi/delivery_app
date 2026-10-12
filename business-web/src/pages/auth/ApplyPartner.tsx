import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";
import { RestaurantLocationMap } from "@/features/restaurant/RestaurantLocationMap";
import { ApiError } from "@/services/api/apiClient";
import { registerRestaurant } from "@/services/api/authApi";

type FormState = {
  owner_name: string;
  email: string;
  password: string;
  confirm_password: string;
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
  confirm_password: "",
  owner_phone: "",
  restaurant_name: "",
  description: "",
  restaurant_phone: "",
  address: "",
  latitude: "",
  longitude: "",
};

function parseCoordinate(value: string, limit: number): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && Math.abs(parsed) <= limit ? parsed : null;
}

/** Accepts "26.0486, 82.6847" — what Google Maps copies when you click a
 * place's coordinates — pasted into either coordinate box. */
function splitCoordinatePair(value: string): [string, string] | null {
  const match = value.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
  return match ? [match[1], match[2]] : null;
}

export default function ApplyPartner() {
  const navigate = useNavigate();
  const { signIn, status } = useSession();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);
  // Bumped whenever coordinates come from outside the map (GPS, typing a
  // pasted pair) so the map remounts centred on them; dragging the marker
  // doesn't bump it, so the map never jumps under the owner's own drag.
  const [mapKey, setMapKey] = useState(0);

  if (status === "authenticated") {
    return <Navigate to="/dashboard" replace />;
  }

  const latitude = parseCoordinate(form.latitude, 90);
  const longitude = parseCoordinate(form.longitude, 180);
  const hasLocation = latitude !== null && longitude !== null;

  function updateField(field: keyof FormState, value: string) {
    if (field === "latitude" || field === "longitude") {
      const pair = splitCoordinatePair(value);
      if (pair) {
        setForm((current) => ({ ...current, latitude: pair[0], longitude: pair[1] }));
        setMapKey((key) => key + 1);
        return;
      }
    }
    setForm((current) => ({ ...current, [field]: value }));
  }

  function fillCurrentLocation() {
    if (!navigator.geolocation) {
      setError("Your browser can't share its location. Enter the coordinates manually.");
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
        setMapKey((key) => key + 1);
        setLocating(false);
      },
      () => {
        setError("Couldn't get your location. Allow location access, or enter the coordinates manually.");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (form.password !== form.confirm_password) {
      setError("Passwords don't match.");
      return;
    }
    if (latitude === null || longitude === null) {
      setError("Set your restaurant's location: use your current location, or enter latitude and longitude.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await registerRestaurant({
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
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to submit your application.");
      setSubmitting(false);
      return;
    }
    // The account exists now — sign straight in so the owner can start
    // setting up their menu while the application is reviewed.
    try {
      await signIn(form.email.trim(), form.password);
      navigate("/dashboard", { replace: true });
    } catch {
      navigate("/login", { replace: true });
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card auth-card-wide">
        <div className="brand-mark">🍽️</div>
        <h1>Become a partner</h1>
        <p className="subtitle">
          Tell us about your restaurant. You can set up your menu right away, and your restaurant appears to customers
          once our team approves it.
        </p>
        <form onSubmit={handleSubmit}>
          <h2 className="form-section-title">Your details</h2>
          <div className="field-row">
            <div className="field">
              <label htmlFor="owner_name">Your name</label>
              <input id="owner_name" required minLength={2} autoComplete="name" value={form.owner_name} onChange={(e) => updateField("owner_name", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="owner_phone">Your phone (optional)</label>
              <input id="owner_phone" type="tel" autoComplete="tel" value={form.owner_phone} onChange={(e) => updateField("owner_phone", e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="email">Email (your login)</label>
            <input id="email" type="email" required autoComplete="username" value={form.email} onChange={(e) => updateField("email", e.target.value)} />
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={form.password}
                onChange={(e) => updateField("password", e.target.value)}
              />
              <span className="hint">At least 8 characters.</span>
            </div>
            <div className="field">
              <label htmlFor="confirm_password">Confirm password</label>
              <input
                id="confirm_password"
                type="password"
                required
                autoComplete="new-password"
                value={form.confirm_password}
                onChange={(e) => updateField("confirm_password", e.target.value)}
              />
            </div>
          </div>

          <h2 className="form-section-title">Your restaurant</h2>
          <div className="field-row">
            <div className="field">
              <label htmlFor="restaurant_name">Restaurant name</label>
              <input id="restaurant_name" required minLength={2} value={form.restaurant_name} onChange={(e) => updateField("restaurant_name", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="restaurant_phone">Restaurant phone</label>
              <input id="restaurant_phone" type="tel" required value={form.restaurant_phone} onChange={(e) => updateField("restaurant_phone", e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="address">Full address</label>
            <input id="address" required minLength={5} autoComplete="street-address" value={form.address} onChange={(e) => updateField("address", e.target.value)} />
          </div>
          <div className="field">
            <button type="button" className="btn-secondary" onClick={fillCurrentLocation} disabled={locating}>
              {locating ? "Locating…" : "📍 Use my current location"}
            </button>
            <span className="hint">Best done while you're at the restaurant. You can drag the pin to adjust it.</span>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="latitude">Latitude</label>
              <input id="latitude" inputMode="decimal" required value={form.latitude} onChange={(e) => updateField("latitude", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="longitude">Longitude</label>
              <input id="longitude" inputMode="decimal" required value={form.longitude} onChange={(e) => updateField("longitude", e.target.value)} />
            </div>
          </div>
          {hasLocation && (
            <div className="apply-map">
              <RestaurantLocationMap
                key={mapKey}
                latitude={latitude}
                longitude={longitude}
                editable
                onLocationChange={(lat, lng) =>
                  setForm((current) => ({ ...current, latitude: lat.toFixed(6), longitude: lng.toFixed(6) }))
                }
              />
            </div>
          )}
          <div className="field">
            <label htmlFor="description">About your restaurant (optional)</label>
            <textarea id="description" maxLength={5000} value={form.description} onChange={(e) => updateField("description", e.target.value)} />
          </div>

          {error && <div className="error-banner" role="alert">{error}</div>}
          <button className="btn-primary" type="submit" disabled={submitting}>
            {submitting ? "Submitting…" : "Submit application"}
          </button>
        </form>
        <p className="auth-footer">
          Already a partner? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
