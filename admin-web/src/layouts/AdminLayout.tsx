import { useState } from "react";
import { Outlet } from "react-router-dom";

import { Breadcrumbs } from "@/components/Breadcrumbs";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

export function AdminLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onNavigate={() => setSidebarOpen(false)} />
      <div className="main-column">
        <Topbar onToggleSidebar={() => setSidebarOpen((v) => !v)} />
        <Breadcrumbs />
        <main className="dashboard">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
