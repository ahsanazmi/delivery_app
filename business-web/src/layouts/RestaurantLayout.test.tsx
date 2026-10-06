import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RestaurantLayout } from "./RestaurantLayout";

// Automated Testing (Phase 44) — this layout's own unread-count badge
// (built in Phase 19) never had a dedicated test; its own underlying
// data-fetching is already covered by Notifications.test.tsx, so this
// file focuses on what's unique to the layout: the badge itself.

const { useSessionMock, getUnreadRestaurantNotificationCountMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  getUnreadRestaurantNotificationCountMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/notificationsApi", () => ({
  getUnreadRestaurantNotificationCount: (...args: unknown[]) => getUnreadRestaurantNotificationCountMock(...args),
}));

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route element={<RestaurantLayout />}>
          <Route path="/dashboard" element={<div>Dashboard content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("RestaurantLayout — notifications badge", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows no badge when there are no unread notifications", async () => {
    useSessionMock.mockReturnValue({ user: { name: "Owner" }, accessToken: "test-token", signOut: vi.fn() });
    getUnreadRestaurantNotificationCountMock.mockResolvedValue({ unread_count: 0 });

    renderLayout();

    await waitFor(() => expect(getUnreadRestaurantNotificationCountMock).toHaveBeenCalledWith("test-token"));
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("shows the unread count as a badge on the Notifications nav link", async () => {
    useSessionMock.mockReturnValue({ user: { name: "Owner" }, accessToken: "test-token", signOut: vi.fn() });
    getUnreadRestaurantNotificationCountMock.mockResolvedValue({ unread_count: 3 });

    renderLayout();

    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
  });

  it("never crashes the portal when the unread-count request fails", async () => {
    useSessionMock.mockReturnValue({ user: { name: "Owner" }, accessToken: "test-token", signOut: vi.fn() });
    getUnreadRestaurantNotificationCountMock.mockRejectedValue(new Error("network down"));

    renderLayout();

    await waitFor(() => expect(getUnreadRestaurantNotificationCountMock).toHaveBeenCalled());
    expect(screen.getByText("Dashboard content")).toBeInTheDocument();
  });

  it("never polls when there is no access token", async () => {
    useSessionMock.mockReturnValue({ user: null, accessToken: null, signOut: vi.fn() });

    renderLayout();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(getUnreadRestaurantNotificationCountMock).not.toHaveBeenCalled();
  });
});
