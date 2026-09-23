import { NavLink } from "react-router-dom";

type NavItem = { to: string; label: string; icon: string };
type NavSection = { label: string; items: NavItem[] };

const SECTIONS: NavSection[] = [
  { label: "Overview", items: [{ to: "/dashboard", label: "Dashboard", icon: "◈" }] },
  {
    label: "People",
    items: [
      { to: "/customers", label: "Customers", icon: "◔" },
      { to: "/restaurant-owners", label: "Owners", icon: "◔" },
      { to: "/riders", label: "Riders", icon: "◔" },
    ],
  },
  {
    label: "Restaurants",
    items: [
      { to: "/restaurants", label: "Restaurants", icon: "▤" },
      { to: "/categories", label: "Categories", icon: "▤" },
      { to: "/service-areas", label: "Service areas", icon: "▤" },
    ],
  },
  {
    label: "Orders & delivery",
    items: [
      { to: "/orders", label: "Orders", icon: "▣" },
      { to: "/delivery-assignments", label: "Deliveries", icon: "▣" },
    ],
  },
  {
    label: "Finance",
    items: [
      { to: "/payments", label: "Payments", icon: "$" },
      { to: "/cod", label: "COD", icon: "$" },
      { to: "/coupons", label: "Coupons", icon: "$" },
    ],
  },
  { label: "Insights", items: [{ to: "/reports", label: "Reports", icon: "▦" }] },
  {
    label: "System",
    items: [
      { to: "/notifications", label: "Notifications", icon: "●" },
      { to: "/audit-logs", label: "Audit logs", icon: "●" },
      { to: "/settings", label: "Settings", icon: "●" },
    ],
  },
];

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  return (
    <>
      <div className={`sidebar-backdrop ${open ? "open" : ""}`} onClick={onNavigate} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-brand">
          <span className="brand-mark">🍵</span>
          Say Hi Chai
        </div>
        <nav className="sidebar-scroll">
          {SECTIONS.map((section) => (
            <div key={section.label}>
              <div className="sidebar-section-label">{section.label}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onNavigate}
                  className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`}
                >
                  <span className="sidebar-icon">{item.icon}</span>
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
