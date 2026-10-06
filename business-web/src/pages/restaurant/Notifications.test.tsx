import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import NotificationsPage from "./Notifications";

const {
  useSessionMock,
  listRestaurantNotificationsMock,
  markRestaurantNotificationReadMock,
  markAllRestaurantNotificationsReadMock,
} = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  listRestaurantNotificationsMock: vi.fn(),
  markRestaurantNotificationReadMock: vi.fn(),
  markAllRestaurantNotificationsReadMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/notificationsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/notificationsApi")>();
  return {
    ...actual,
    listRestaurantNotifications: listRestaurantNotificationsMock,
    markRestaurantNotificationRead: markRestaurantNotificationReadMock,
    markAllRestaurantNotificationsRead: markAllRestaurantNotificationsReadMock,
  };
});

function renderNotificationsPage() {
  return render(
    <MemoryRouter>
      <NotificationsPage />
    </MemoryRouter>,
  );
}

describe("Restaurant owner — Notifications page", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders notifications from the API with an unread badge for unread rows", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    listRestaurantNotificationsMock.mockResolvedValue([
      {
        id: "notif-1", type: "restaurant_new_order", title: "New order #SHC-0001",
        body: "You have a new order.", order_id: "order-1", data: null,
        is_read: false, created_at: new Date().toISOString(), read_at: null,
      },
    ]);

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByText(/New order #SHC-0001/)).toBeInTheDocument();
      expect(screen.getByText(/1 UNREAD/)).toBeInTheDocument();
    });
  });

  it("shows the backend's own error message, not a generic crash, when notifications fail to load", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    const { ApiError } = await import("@/services/api/apiClient");
    listRestaurantNotificationsMock.mockRejectedValue(new ApiError("Restaurant not found", 404));

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Restaurant not found");
    });
  });

  it("shows an empty state, not a blank page, when there are no notifications", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    listRestaurantNotificationsMock.mockResolvedValue([]);

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByText("No notifications yet.")).toBeInTheDocument();
    });
  });

  it("marks all notifications read when the button is clicked", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    listRestaurantNotificationsMock.mockResolvedValue([
      {
        id: "notif-1", type: "system", title: "Heads up", body: "Something happened.",
        order_id: null, data: null, is_read: false, created_at: new Date().toISOString(), read_at: null,
      },
    ]);
    markAllRestaurantNotificationsReadMock.mockResolvedValue({ updated: 1 });

    renderNotificationsPage();

    await waitFor(() => expect(screen.getByText(/1 UNREAD/)).toBeInTheDocument());

    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText("Mark all read"));

    await waitFor(() => {
      expect(markAllRestaurantNotificationsReadMock).toHaveBeenCalledWith("test-token");
      expect(screen.queryByText(/UNREAD/)).not.toBeInTheDocument();
    });
  });
});
