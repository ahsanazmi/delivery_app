import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminCommissionConfig,
  getAdminSettings,
  setAdminDefaultCommission,
  updateAdminSettings,
  type AdminCommissionConfig,
  type AdminCommissionType,
  type AdminPlatformSettings,
} from "@/services/api/adminApi";

export default function Settings() {
  const { accessToken } = useSession();
  const [settings, setSettings] = useState<AdminPlatformSettings | null>(null);
  const [commissions, setCommissions] = useState<AdminCommissionConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    platform_name: "",
    support_email: "",
    support_phone: "",
    default_delivery_fee: "",
    default_minimum_order: "",
    notifications_enabled: true,
    maintenance_mode: false,
  });

  const [commissionType, setCommissionType] = useState<AdminCommissionType>("PERCENTAGE");
  const [commissionValue, setCommissionValue] = useState("");
  const [savingCommission, setSavingCommission] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const [settingsResponse, commissionResponse] = await Promise.all([
        getAdminSettings(accessToken),
        getAdminCommissionConfig(accessToken),
      ]);
      setSettings(settingsResponse);
      setCommissions(commissionResponse);
      setForm({
        platform_name: settingsResponse.platform_name,
        support_email: settingsResponse.support_email ?? "",
        support_phone: settingsResponse.support_phone ?? "",
        default_delivery_fee: settingsResponse.default_delivery_fee,
        default_minimum_order: settingsResponse.default_minimum_order,
        notifications_enabled: settingsResponse.notifications_enabled,
        maintenance_mode: settingsResponse.maintenance_mode,
      });
      if (commissionResponse.default) {
        setCommissionType(commissionResponse.default.commission_type);
        setCommissionValue(commissionResponse.default.value);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load settings.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!accessToken || !settings) return;
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await updateAdminSettings(accessToken, {
        platform_name: form.platform_name,
        support_email: form.support_email || undefined,
        support_phone: form.support_phone || undefined,
        default_delivery_fee: form.default_delivery_fee,
        default_minimum_order: form.default_minimum_order,
        notifications_enabled: form.notifications_enabled,
        maintenance_mode: form.maintenance_mode,
        reason: "Updated from Admin Settings page",
      });
      setSettings(updated);
      setSavedMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save settings.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveCommission(e: React.FormEvent) {
    e.preventDefault();
    if (!accessToken || !commissionValue.trim()) return;
    setSavingCommission(true);
    setError(null);
    setSavedMessage(null);
    try {
      const updated = await setAdminDefaultCommission(accessToken, commissionType, commissionValue.trim());
      setCommissions(updated);
      setSavedMessage("Default commission saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save default commission.");
    } finally {
      setSavingCommission(false);
    }
  }

  if (loading) {
    return <LoadingIndicator />;
  }

  return (
    <>
      <h2 className="section-title">Settings</h2>
      <p className="muted" style={{ marginTop: -8, marginBottom: 20 }}>
        Platform-wide, non-secret configuration. Infrastructure secrets (API keys, database credentials) stay environment-based and are never editable here.
      </p>

      {error && <ErrorState message={error} onRetry={load} />}
      {savedMessage && (
        <div className="status-pill status-active" style={{ display: "inline-block", marginBottom: 16 }}>
          {savedMessage}
        </div>
      )}

      <form onSubmit={handleSave}>
        <h3 className="section-title" style={{ fontSize: 16 }}>General</h3>
        <div className="field">
          <label>Platform name</label>
          <input
            value={form.platform_name}
            onChange={(e) => setForm((f) => ({ ...f, platform_name: e.target.value }))}
          />
        </div>
        <div className="field">
          <label>Support email</label>
          <input
            type="email"
            value={form.support_email}
            onChange={(e) => setForm((f) => ({ ...f, support_email: e.target.value }))}
            placeholder="support@example.com"
          />
        </div>
        <div className="field">
          <label>Support phone</label>
          <input
            value={form.support_phone}
            onChange={(e) => setForm((f) => ({ ...f, support_phone: e.target.value }))}
            placeholder="+91XXXXXXXXXX"
          />
        </div>

        <h3 className="section-title" style={{ fontSize: 16, marginTop: 24 }}>Order configuration</h3>
        <p className="muted" style={{ marginTop: -8 }}>
          Used as the fallback for a new restaurant that doesn't set its own value — never overwrites an existing restaurant's own fee or minimum.
        </p>
        <div className="field">
          <label>Default delivery fee (₹)</label>
          <input
            type="number" step="0.01" min="0"
            value={form.default_delivery_fee}
            onChange={(e) => setForm((f) => ({ ...f, default_delivery_fee: e.target.value }))}
          />
        </div>
        <div className="field">
          <label>Default minimum order (₹)</label>
          <input
            type="number" step="0.01" min="0"
            value={form.default_minimum_order}
            onChange={(e) => setForm((f) => ({ ...f, default_minimum_order: e.target.value }))}
          />
        </div>

        <h3 className="section-title" style={{ fontSize: 16, marginTop: 24 }}>Notification configuration</h3>
        <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            checked={form.notifications_enabled}
            onChange={(e) => setForm((f) => ({ ...f, notifications_enabled: e.target.checked }))}
          />
          <label style={{ margin: 0 }}>Notifications enabled platform-wide</label>
        </div>
        <p className="muted" style={{ marginTop: -4 }}>
          Turning this off stops every order-status, new-delivery, promotional and admin-alert notification from being created or pushed until it's turned back on.
        </p>

        <h3 className="section-title" style={{ fontSize: 16, marginTop: 24 }}>Business rules</h3>
        <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            checked={form.maintenance_mode}
            onChange={(e) => setForm((f) => ({ ...f, maintenance_mode: e.target.checked }))}
          />
          <label style={{ margin: 0 }}>Maintenance mode</label>
        </div>
        <p className="muted" style={{ marginTop: -4 }}>
          When enabled, blocks every new order platform-wide with a friendly message — existing in-flight orders are unaffected.
        </p>

        <button className="btn-secondary" type="submit" disabled={saving} style={{ marginTop: 16 }}>
          {saving ? "Saving…" : "Save settings"}
        </button>
      </form>

      <h3 className="section-title" style={{ fontSize: 16, marginTop: 32 }}>Default commission</h3>
      <p className="muted" style={{ marginTop: -8 }}>
        Managed separately from the settings above (see Admin Portal Phase 17) — applies to every order unless a restaurant has its own override.
      </p>
      <form className="filter-bar" onSubmit={handleSaveCommission} style={{ alignItems: "flex-end" }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Type</label>
          <select
            className="filter-input"
            value={commissionType}
            onChange={(e) => setCommissionType(e.target.value as AdminCommissionType)}
          >
            <option value="PERCENTAGE">Percentage</option>
            <option value="FIXED">Fixed amount</option>
          </select>
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>{commissionType === "PERCENTAGE" ? "Percentage" : "Amount (₹)"}</label>
          <input
            type="number" step="0.01" min="0"
            value={commissionValue}
            onChange={(e) => setCommissionValue(e.target.value)}
          />
        </div>
        <button className="btn-secondary" type="submit" disabled={savingCommission || !commissionValue.trim()}>
          {savingCommission ? "Saving…" : "Save default commission"}
        </button>
      </form>
      {commissions && !commissions.default && (
        <p className="muted">No platform default commission has been configured yet.</p>
      )}
      {commissions && commissions.restaurant_overrides.length > 0 && (
        <p className="muted">
          {commissions.restaurant_overrides.length} restaurant(s) have their own commission override, unaffected by this default.
        </p>
      )}
    </>
  );
}
