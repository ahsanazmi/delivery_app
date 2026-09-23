import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useSession } from "@/features/auth/session-context";

export function RestaurantLayout() {
  const navigate = useNavigate();
  const { user, signOut } = useSession();

  async function handleLogout() {
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <div>
          <h1>Restaurant portal</h1>
          {user && <p className="subtitle" style={{ margin: "4px 0 0" }}>{user.name}</p>}
        </div>
        <button className="btn-secondary" onClick={handleLogout}>
          Logout
        </button>
      </div>
      <nav className="portal-nav">
        <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Dashboard
        </NavLink>
        <NavLink to="/profile" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Restaurant Profile
        </NavLink>
        <NavLink to="/hours" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Operating Hours
        </NavLink>
        <NavLink to="/categories" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Categories
        </NavLink>
        <NavLink to="/products" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Products
        </NavLink>
        <NavLink to="/orders" className={({ isActive }) => (isActive ? "portal-nav-link active" : "portal-nav-link")}>
          Orders
        </NavLink>
      </nav>
      <Outlet />
    </div>
  );
}
