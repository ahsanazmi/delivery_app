import { FormEvent, useCallback, useEffect, useState } from "react";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
    DAY_NAMES,
    emptyWeek,
    getRestaurantHours,
    updateRestaurantHours,
    type OperatingHourEntry,
} from "@/services/api/hoursApi";

function sortByDay(hours: OperatingHourEntry[]): OperatingHourEntry[] {
  return [...hours].sort((a, b) => a.day_of_week - b.day_of_week);
}

export default function OperatingHoursPage() {
  const { accessToken } = useSession();
  const [week, setWeek] = useState<OperatingHourEntry[]>(emptyWeek());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getRestaurantHours(accessToken);
      if (data.hours.length === 7) {
        setWeek(
          sortByDay(
            data.hours.map((h) => ({
              day_of_week: h.day_of_week,
              is_closed: h.is_closed,
              open_time: h.open_time,
              close_time: h.close_time,
            })),
          ),
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load operating hours.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  function updateDay(dayOfWeek: number, changes: Partial<OperatingHourEntry>) {
    setWeek((current) =>
      current.map((entry) => (entry.day_of_week === dayOfWeek ? { ...entry, ...changes } : entry)),
    );
  }

  function copyMondayToAll() {
    const monday = week.find((entry) => entry.day_of_week === 0);
    if (!monday) return;
    setWeek((current) =>
      current.map((entry) => ({
        ...entry,
        is_closed: monday.is_closed,
        open_time: monday.open_time,
        close_time: monday.close_time,
      })),
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!accessToken) return;

    setSaving(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const updated = await updateRestaurantHours(accessToken, week);
      setWeek(
        sortByDay(
          updated.hours.map((h) => ({
            day_of_week: h.day_of_week,
            is_closed: h.is_closed,
            open_time: h.open_time,
            close_time: h.close_time,
          })),
        ),
      );
      setSuccessMessage("Operating hours updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save operating hours.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="page-center">Loading operating hours…</p>;
  }

  return (
    <div className="operating-hours">
      <h2 className="section-title">Operating hours</h2>
      <p className="subtitle" style={{ marginBottom: 20 }}>
        Orders are only accepted during these hours, even if the restaurant is toggled "Open" on the dashboard.
      </p>

      {successMessage && <div className="success-banner">{successMessage}</div>}
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="profile-form">
        <div className="hours-table">
          {week.map((entry) => (
            <div className="hours-row" key={entry.day_of_week}>
              <div className="hours-day">{DAY_NAMES[entry.day_of_week]}</div>
              <label className="hours-closed-toggle">
                <input
                  type="checkbox"
                  checked={entry.is_closed}
                  onChange={(e) => updateDay(entry.day_of_week, { is_closed: e.target.checked })}
                />
                Closed
              </label>
              {!entry.is_closed && (
                <div className="hours-time-inputs">
                  <input
                    type="time"
                    value={(entry.open_time ?? "10:00:00").slice(0, 5)}
                    onChange={(e) => updateDay(entry.day_of_week, { open_time: `${e.target.value}:00` })}
                    required
                  />
                  <span className="muted">to</span>
                  <input
                    type="time"
                    value={(entry.close_time ?? "22:00:00").slice(0, 5)}
                    onChange={(e) => updateDay(entry.day_of_week, { close_time: `${e.target.value}:00` })}
                    required
                  />
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="profile-form-actions" style={{ justifyContent: "space-between" }}>
          <button type="button" className="btn-secondary" onClick={copyMondayToAll}>
            Copy Monday to all days
          </button>
          <button type="submit" className="btn-primary" style={{ width: "auto", padding: "0 24px" }} disabled={saving}>
            {saving ? "Saving…" : "Save hours"}
          </button>
        </div>
      </form>
    </div>
  );
}
