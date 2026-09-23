import { Link, useLocation } from "react-router-dom";

const SECTION_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  customers: "Customers",
  restaurants: "Restaurants",
  "restaurant-owners": "Restaurant Owners",
  riders: "Riders",
  orders: "Orders",
  "delivery-assignments": "Delivery Assignments",
  payments: "Payments",
  cod: "COD Reconciliation",
  categories: "Categories",
  "service-areas": "Service Areas",
  coupons: "Coupons",
  reports: "Reports",
  notifications: "Notifications",
  "audit-logs": "Audit Logs",
  settings: "Settings",
};

const DETAIL_LABELS: Record<string, string> = {
  customers: "Customer",
  restaurants: "Restaurant",
  "restaurant-owners": "Owner",
  riders: "Rider",
  orders: "Order",
  "delivery-assignments": "Assignment",
  payments: "Payment",
};

export function Breadcrumbs() {
  const { pathname } = useLocation();
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return null;

  const section = segments[0];
  const sectionLabel = SECTION_LABELS[section] ?? section;
  const hasDetail = segments.length > 1;

  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/dashboard">Home</Link>
      <span className="sep">/</span>
      {hasDetail ? (
        <>
          <Link to={`/${section}`}>{sectionLabel}</Link>
          <span className="sep">/</span>
          <span className="current">{DETAIL_LABELS[section] ?? "Details"}</span>
        </>
      ) : (
        <span className="current">{sectionLabel}</span>
      )}
    </nav>
  );
}
