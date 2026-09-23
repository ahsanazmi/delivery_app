import { useNavigate } from "react-router-dom";

import { useConfirm } from "@/components/dialog/ConfirmProvider";
import { useSession } from "@/features/auth/session-context";

export function Topbar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const navigate = useNavigate();
  const { user, signOut } = useSession();
  const { confirm } = useConfirm();

  async function handleLogout() {
    const ok = await confirm({ title: "Log out?", message: "You'll need to sign in again to access the admin portal." });
    if (!ok) return;
    await signOut();
    navigate("/login", { replace: true });
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="sidebar-toggle" onClick={onToggleSidebar} aria-label="Toggle navigation">
          ☰
        </button>
        <span className="topbar-title">Admin Portal</span>
      </div>
      <div className="topbar-right">
        {user && (
          <div className="topbar-user">
            <span className="name">{user.name}</span>
            <span className="role">{user.role}</span>
          </div>
        )}
        <button className="btn-secondary" onClick={handleLogout}>
          Logout
        </button>
      </div>
    </header>
  );
}
