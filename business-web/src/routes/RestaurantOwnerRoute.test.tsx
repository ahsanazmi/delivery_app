import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { RestaurantOwnerRoute } from "./RestaurantOwnerRoute";

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route element={<RestaurantOwnerRoute />}>
          <Route path="/dashboard" element={<div>Owner dashboard content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("RestaurantOwnerRoute", () => {
  it("redirects an anonymous visitor to /login instead of rendering the protected page", () => {
    useSessionMock.mockReturnValue({ status: "anonymous", user: null, signOut: vi.fn() });
    renderGuard();
    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Owner dashboard content")).not.toBeInTheDocument();
  });

  it("shows a loading state instead of the protected page while the session is still resolving", () => {
    useSessionMock.mockReturnValue({ status: "loading", user: null, signOut: vi.fn() });
    renderGuard();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByText("Owner dashboard content")).not.toBeInTheDocument();
  });

  it("blocks an authenticated non-owner (role routing) with a 'not authorized' screen, not the protected page", () => {
    useSessionMock.mockReturnValue({
      status: "authenticated",
      user: { id: "u1", role: "CUSTOMER", name: "A Customer" },
      signOut: vi.fn(),
    });
    renderGuard();
    expect(screen.getByText(/not authorized/i)).toBeInTheDocument();
    expect(screen.queryByText("Owner dashboard content")).not.toBeInTheDocument();
  });

  it("renders the protected page for an authenticated restaurant owner", () => {
    useSessionMock.mockReturnValue({
      status: "authenticated",
      user: { id: "u2", role: "RESTAURANT_OWNER", name: "An Owner" },
      signOut: vi.fn(),
    });
    renderGuard();
    expect(screen.getByText("Owner dashboard content")).toBeInTheDocument();
  });
});
