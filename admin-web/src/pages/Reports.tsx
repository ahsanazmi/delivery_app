import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
  getAdminCustomersReport,
  getAdminOrdersReport,
  getAdminReportsOverview,
  getAdminRestaurantsReport,
  getAdminRevenueReport,
  getAdminRidersReport,
  type AdminCustomersReport,
  type AdminOrdersReport,
  type AdminReportsOverview,
  type AdminRestaurantsReport,
  type AdminRevenueReport,
  type AdminRidersReport,
} from "@/services/api/adminApi";

type Tab = "overview" | "orders" | "revenue" | "restaurants" | "riders" | "customers";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "orders", label: "Orders" },
  { id: "revenue", label: "Revenue" },
  { id: "restaurants", label: "Restaurants" },
  { id: "riders", label: "Riders" },
  { id: "customers", label: "Customers" },
];

// A small, dependency-free bar chart — this admin app has no charting
// library installed, and a handful of CSS bars is enough for daily counts
// or amounts without adding one.
function BarChart({ points, formatValue }: { points: { label: string; value: number }[]; formatValue?: (v: number) => string }) {
  if (points.length === 0) {
    return <div className="empty-state">No data for this range.</div>;
  }
  const max = Math.max(...points.map((p) => p.value), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 160, padding: "12px 0", overflowX: "auto" }}>
      {points.map((p) => (
        <div key={p.label} style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 28 }} title={`${p.label}: ${formatValue ? formatValue(p.value) : p.value}`}>
          <div
            style={{
              width: 18,
              height: Math.max(2, (p.value / max) * 120),
              background: "var(--brand)",
              borderRadius: "3px 3px 0 0",
              transition: "opacity 0.15s ease",
            }}
          />
          <div className="muted" style={{ fontSize: 10, marginTop: 4, whiteSpace: "nowrap" }}>
            {p.label.slice(5)}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Reports() {
  const { accessToken } = useSession();
  const [tab, setTab] = useState<Tab>("overview");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<AdminReportsOverview | null>(null);
  const [orders, setOrders] = useState<AdminOrdersReport | null>(null);
  const [revenue, setRevenue] = useState<AdminRevenueReport | null>(null);
  const [restaurants, setRestaurants] = useState<AdminRestaurantsReport | null>(null);
  const [riders, setRiders] = useState<AdminRidersReport | null>(null);
  const [customers, setCustomers] = useState<AdminCustomersReport | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
    try {
      const [ov, ord, rev, rest, rid, cust] = await Promise.all([
        getAdminReportsOverview(accessToken, params),
        getAdminOrdersReport(accessToken, params),
        getAdminRevenueReport(accessToken, params),
        getAdminRestaurantsReport(accessToken, params),
        getAdminRidersReport(accessToken, params),
        getAdminCustomersReport(accessToken, params),
      ]);
      setOverview(ov);
      setOrders(ord);
      setRevenue(rev);
      setRestaurants(rest);
      setRiders(rid);
      setCustomers(cust);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load reports.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <h2 className="section-title">Reports &amp; analytics</h2>

      {error && <ErrorState message={error} onRetry={load} />}

      <form className="filter-bar" onSubmit={(e) => e.preventDefault()}>
        <label className="filter-date-label">
          From
          <input className="filter-input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label className="filter-date-label">
          To
          <input className="filter-input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        {(dateFrom || dateTo) && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setDateFrom("");
              setDateTo("");
            }}
          >
            Clear (all time)
          </button>
        )}
      </form>

      <div className="portal-nav" style={{ marginBottom: 20 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={t.id === tab ? "portal-nav-link active" : "portal-nav-link"}
            style={{ background: "none", border: "none", cursor: "pointer", font: "inherit" }}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingIndicator />
      ) : (
        <>
          {tab === "overview" && overview && (
            <>
              <div className="stats-grid">
                <div className="stat-card"><div className="label">Total orders</div><div className="value">{overview.total_orders}</div></div>
                <div className="stat-card"><div className="label">Completed orders</div><div className="value">{overview.completed_orders}</div></div>
                <div className="stat-card"><div className="label">Cancelled orders</div><div className="value">{overview.cancelled_orders}</div></div>
                <div className="stat-card"><div className="label">Revenue</div><div className="value">₹{overview.revenue}</div></div>
                <div className="stat-card"><div className="label">Platform commission</div><div className="value">₹{overview.platform_commission}</div></div>
                <div className="stat-card"><div className="label">Restaurant earnings</div><div className="value">₹{overview.restaurant_earnings}</div></div>
                <div className="stat-card"><div className="label">Rider earnings</div><div className="value">₹{overview.rider_earnings}</div></div>
                <div className="stat-card"><div className="label">COD outstanding</div><div className="value">₹{overview.cod_outstanding}</div></div>
                <div className="stat-card"><div className="label">Customer growth</div><div className="value">{overview.customer_growth}</div></div>
                <div className="stat-card"><div className="label">Restaurant growth</div><div className="value">{overview.restaurant_growth}</div></div>
                <div className="stat-card"><div className="label">Rider growth</div><div className="value">{overview.rider_growth}</div></div>
              </div>
              <p className="muted">
                Revenue, commission, and restaurant earnings count delivered orders only. COD outstanding is a live
                platform-wide balance and is not limited by the date range above.
              </p>
            </>
          )}

          {tab === "orders" && orders && (
            <>
              <div className="stats-grid">
                <div className="stat-card"><div className="label">Total</div><div className="value">{orders.total_orders}</div></div>
                <div className="stat-card"><div className="label">Completed</div><div className="value">{orders.completed_orders}</div></div>
                <div className="stat-card"><div className="label">Cancelled</div><div className="value">{orders.cancelled_orders}</div></div>
                <div className="stat-card"><div className="label">Rejected</div><div className="value">{orders.rejected_orders}</div></div>
                <div className="stat-card"><div className="label">In progress</div><div className="value">{orders.in_progress_orders}</div></div>
              </div>

              <h2 className="section-title">Orders per day</h2>
              <BarChart points={orders.orders_by_day.map((d) => ({ label: d.date, value: d.count }))} />

              <h2 className="section-title">Status breakdown</h2>
              <div className="table-scroll">
                <table className="admin-table">
                  <thead><tr><th>Status</th><th>Count</th></tr></thead>
                  <tbody>
                    {orders.status_breakdown.map((row) => (
                      <tr key={row.status}><td>{row.status.replaceAll("_", " ")}</td><td>{row.count}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {tab === "revenue" && revenue && (
            <>
              <div className="stats-grid">
                <div className="stat-card"><div className="label">Revenue</div><div className="value">₹{revenue.revenue}</div></div>
                <div className="stat-card"><div className="label">Platform commission</div><div className="value">₹{revenue.platform_commission}</div></div>
                <div className="stat-card"><div className="label">Restaurant earnings</div><div className="value">₹{revenue.restaurant_earnings}</div></div>
                <div className="stat-card"><div className="label">Rider earnings</div><div className="value">₹{revenue.rider_earnings}</div></div>
              </div>
              <h2 className="section-title">Revenue per day</h2>
              <BarChart
                points={revenue.revenue_by_day.map((d) => ({ label: d.date, value: Number(d.amount) }))}
                formatValue={(v) => `₹${v.toFixed(2)}`}
              />
            </>
          )}

          {tab === "restaurants" && restaurants && (
            <>
              <div className="stats-grid">
                <div className="stat-card"><div className="label">Total restaurants</div><div className="value">{restaurants.total_restaurants}</div></div>
                <div className="stat-card"><div className="label">Active restaurants</div><div className="value">{restaurants.active_restaurants}</div></div>
                <div className="stat-card"><div className="label">New (growth)</div><div className="value">{restaurants.new_restaurants}</div></div>
              </div>
              <h2 className="section-title">Growth per day</h2>
              <BarChart points={restaurants.growth_by_day.map((d) => ({ label: d.date, value: d.count }))} />

              <h2 className="section-title">Top restaurants by revenue</h2>
              <div className="table-scroll">
                <table className="admin-table">
                  <thead><tr><th>Restaurant</th><th>Orders</th><th>Revenue</th></tr></thead>
                  <tbody>
                    {restaurants.top_restaurants.map((r) => (
                      <tr key={r.restaurant_id}><td>{r.restaurant_name}</td><td>{r.order_count}</td><td>₹{r.revenue}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {tab === "riders" && riders && (
            <>
              <div className="stats-grid">
                <div className="stat-card"><div className="label">Total riders</div><div className="value">{riders.total_riders}</div></div>
                <div className="stat-card"><div className="label">Active riders</div><div className="value">{riders.active_riders}</div></div>
                <div className="stat-card"><div className="label">New (growth)</div><div className="value">{riders.new_riders}</div></div>
                <div className="stat-card"><div className="label">Rider earnings</div><div className="value">₹{riders.rider_earnings}</div></div>
                <div className="stat-card"><div className="label">COD outstanding</div><div className="value">₹{riders.cod_outstanding}</div></div>
              </div>
              <h2 className="section-title">Growth per day</h2>
              <BarChart points={riders.growth_by_day.map((d) => ({ label: d.date, value: d.count }))} />

              <h2 className="section-title">Top riders by earnings</h2>
              <div className="table-scroll">
                <table className="admin-table">
                  <thead><tr><th>Rider</th><th>Deliveries</th><th>Earnings</th></tr></thead>
                  <tbody>
                    {riders.top_riders.map((r) => (
                      <tr key={r.rider_id}><td>{r.rider_name}</td><td>{r.deliveries_count}</td><td>₹{r.earnings}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {tab === "customers" && customers && (
            <>
              <div className="stats-grid">
                <div className="stat-card"><div className="label">Total customers</div><div className="value">{customers.total_customers}</div></div>
                <div className="stat-card"><div className="label">New (growth)</div><div className="value">{customers.new_customers}</div></div>
              </div>
              <h2 className="section-title">Growth per day</h2>
              <BarChart points={customers.growth_by_day.map((d) => ({ label: d.date, value: d.count }))} />

              <h2 className="section-title">Top customers by spend</h2>
              <div className="table-scroll">
                <table className="admin-table">
                  <thead><tr><th>Customer</th><th>Orders</th><th>Total spent</th></tr></thead>
                  <tbody>
                    {customers.top_customers.map((c) => (
                      <tr key={c.customer_id}><td>{c.customer_name}</td><td>{c.order_count}</td><td>₹{c.total_spent}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
