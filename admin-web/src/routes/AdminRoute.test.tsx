import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AdminRoute } from "./AdminRoute";

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route element={<AdminRoute />}>
          <Route path="/dashboard" element={<div>Admin dashboard content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminRoute", () => {
  it("redirects an anonymous visitor to /login instead of rendering the protected page", () => {
    useSessionMock.mockReturnValue({ status: "anonymous", user: null, signOut: vi.fn() });
    renderGuard();
    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Admin dashboard content")).not.toBeInTheDocument();
  });

  it("blocks an authenticated non-admin (role routing) — a rider, restaurant owner, or customer session must never see admin pages", () => {
    for (const role of ["RIDER", "RESTAURANT_OWNER", "CUSTOMER"]) {
      useSessionMock.mockReturnValue({
        status: "authenticated",
        user: { id: "u1", role, name: "Someone" },
        signOut: vi.fn(),
      });
      const { unmount } = renderGuard();
      expect(screen.getByText(/not authorized/i)).toBeInTheDocument();
      expect(screen.queryByText("Admin dashboard content")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("renders the protected page for an authenticated admin", () => {
    useSessionMock.mockReturnValue({
      status: "authenticated",
      user: { id: "u2", role: "ADMIN", name: "An Admin" },
      signOut: vi.fn(),
    });
    renderGuard();
    expect(screen.getByText("Admin dashboard content")).toBeInTheDocument();
  });
});
