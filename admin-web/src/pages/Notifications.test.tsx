import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Notifications from "./Notifications";

// Automated Testing (Phase 44) — this page had no test at all despite
// existing since earlier work on the Admin Portal; covers what this
// phase's own checklist names: the list itself, mark read, mark all
// read, and the unread count the header badge is built from.

const { useSessionMock, getAdminNotificationsMock, markAdminNotificationReadMock, markAllAdminNotificationsReadMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  getAdminNotificationsMock: vi.fn(),
  markAdminNotificationReadMock: vi.fn(),
  markAllAdminNotificationsReadMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/adminApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/adminApi")>();
  return {
    ...actual,
    getAdminNotifications: getAdminNotificationsMock,
    markAdminNotificationRead: markAdminNotificationReadMock,
    markAllAdminNotificationsRead: markAllAdminNotificationsReadMock,
  };
});

function baseNotification(overrides: Record<string, unknown> = {}) {
  return {
    id: "notif-1",
    type: "order_issue",
    title: "Order issue",
    body: "Order SHC-0001 was cancelled.",
    order_id: "order-1",
    data: null,
    is_read: false,
    created_at: new Date().toISOString(),
    read_at: null,
    ...overrides,
  };
}

describe("Admin Notifications page", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  beforeEach(() => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
  });

  it("renders the notification list from the API", async () => {
    getAdminNotificationsMock.mockResolvedValue([baseNotification()]);
    render(<Notifications />);

    await waitFor(() => {
      expect(screen.getByText("Order issue")).toBeInTheDocument();
      expect(screen.getByText("Order SHC-0001 was cancelled.")).toBeInTheDocument();
    });
  });

  it("shows an empty state, not a blank page, when there are no notifications", async () => {
    getAdminNotificationsMock.mockResolvedValue([]);
    render(<Notifications />);

    await waitFor(() => expect(screen.getByText("No notifications yet.")).toBeInTheDocument());
  });

  it("marks a single notification read", async () => {
    getAdminNotificationsMock.mockResolvedValue([baseNotification()]);
    markAdminNotificationReadMock.mockResolvedValue(baseNotification({ is_read: true, read_at: new Date().toISOString() }));
    render(<Notifications />);

    await waitFor(() => expect(screen.getByText("Mark read")).toBeInTheDocument());
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText("Mark read"));

    await waitFor(() => expect(markAdminNotificationReadMock).toHaveBeenCalledWith("test-token", "notif-1"));
  });

  it("marks all notifications read and shows the updated unread count", async () => {
    getAdminNotificationsMock.mockResolvedValue([
      baseNotification({ id: "n1" }),
      baseNotification({ id: "n2", title: "Second issue" }),
    ]);
    markAllAdminNotificationsReadMock.mockResolvedValue({ updated: 2 });
    render(<Notifications />);

    await waitFor(() => expect(screen.getByText(/Mark all read \(2\)/)).toBeInTheDocument());
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(screen.getByText(/Mark all read/));

    await waitFor(() => expect(markAllAdminNotificationsReadMock).toHaveBeenCalledWith("test-token"));
  });

  it("shows the backend's own error message, not a generic crash, when loading fails", async () => {
    const { ApiError } = await import("@/services/api/apiClient");
    getAdminNotificationsMock.mockRejectedValue(new ApiError("Session expired", 401));
    render(<Notifications />);

    await waitFor(() => expect(screen.getByText("Session expired")).toBeInTheDocument());
  });
});
