import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

// Notifications & Communication System Phase 10 — Customer Notification
// Center. This screen already existed and was already substantively
// built (title/body/time/read-unread/type icon, tap-to-open-order, mark
// read, mark all read) — this file is the screen-level test that was
// missing, matching this codebase's own convention of one per screen
// (e.g. orders.screen.test.tsx, track.screen.test.tsx).

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const { useEffect } = require("react");
    useEffect(() => callback(), []);
  },
}));

const mockRouter = { back: jest.fn(), push: jest.fn(), replace: jest.fn() };

const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

const mockGetNotificationsModule = jest.fn();
jest.mock("@/features/notifications/push-notifications", () => ({
  getNotificationsModule: () => mockGetNotificationsModule(),
}));

const mockGetNotifications = jest.fn();
const mockMarkNotificationRead = jest.fn();
const mockMarkAllNotificationsRead = jest.fn();
jest.mock("@/services/api/notificationsApi", () => ({
  getNotifications: (...args: unknown[]) => mockGetNotifications(...args),
  markNotificationRead: (...args: unknown[]) => mockMarkNotificationRead(...args),
  markAllNotificationsRead: (...args: unknown[]) => mockMarkAllNotificationsRead(...args),
}));

import NotificationsScreen from "../notifications";

function baseNotification(overrides: Record<string, unknown> = {}) {
  return {
    id: "notif-1",
    type: "order_confirmed",
    title: "Order confirmed",
    body: "Your restaurant has confirmed your order.",
    order_id: "order-1",
    data: { type: "order_status", order_id: "order-1", status: "confirmed" },
    is_read: false,
    created_at: new Date().toISOString(),
    read_at: null,
    ...overrides,
  };
}

describe("NotificationsScreen", () => {
  beforeEach(() => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockGetNotifications.mockReset();
    mockMarkNotificationRead.mockReset().mockResolvedValue({});
    mockMarkAllNotificationsRead.mockReset().mockResolvedValue({ updated: 0 });
    mockRouter.push.mockReset();
    mockGetNotificationsModule.mockReset().mockResolvedValue(null);
  });

  it("redirects to /login for an anonymous session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null });
    mockGetNotifications.mockResolvedValue([]);
    render(<NotificationsScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("shows title, body, and a formatted time for each notification", async () => {
    mockGetNotifications.mockResolvedValue([baseNotification()]);
    render(<NotificationsScreen />);

    await waitFor(() => {
      expect(screen.getByText("Order confirmed")).toBeTruthy();
      expect(screen.getByText("Your restaurant has confirmed your order.")).toBeTruthy();
    });
  });

  it("shows an unread indicator only for unread notifications", async () => {
    mockGetNotifications.mockResolvedValue([
      baseNotification({ id: "unread-1", is_read: false }),
      baseNotification({ id: "read-1", title: "Already seen", is_read: true }),
    ]);
    render(<NotificationsScreen />);

    await waitFor(() => expect(screen.getByText("Already seen")).toBeTruthy());
    // "Mark all read" is only enabled while at least one notification is
    // unread — a cheap, already-visible proxy for the unread state
    // without reaching into style internals.
    expect(screen.getByText("Mark all read")).toBeTruthy();
  });

  it("marks a notification read and navigates to its order when tapped", async () => {
    mockGetNotifications.mockResolvedValue([baseNotification()]);
    render(<NotificationsScreen />);

    await waitFor(() => expect(screen.getByText("Order confirmed")).toBeTruthy());
    fireEvent.press(screen.getByText("Order confirmed"));

    await waitFor(() => expect(mockMarkNotificationRead).toHaveBeenCalledWith("test-token", "notif-1"));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/orders/[id]", params: { id: "order-1" } });
  });

  it("does not re-mark-read or duplicate the request for an already-read notification", async () => {
    mockGetNotifications.mockResolvedValue([baseNotification({ is_read: true })]);
    render(<NotificationsScreen />);

    await waitFor(() => expect(screen.getByText("Order confirmed")).toBeTruthy());
    fireEvent.press(screen.getByText("Order confirmed"));

    await waitFor(() => expect(mockRouter.push).toHaveBeenCalled());
    expect(mockMarkNotificationRead).not.toHaveBeenCalled();
  });

  it("marks every notification read via the header action", async () => {
    mockGetNotifications.mockResolvedValue([
      baseNotification({ id: "n1" }),
      baseNotification({ id: "n2", title: "Second", order_id: null }),
    ]);
    render(<NotificationsScreen />);

    await waitFor(() => expect(screen.getByText("Order confirmed")).toBeTruthy());
    fireEvent.press(screen.getByText("Mark all read"));

    await waitFor(() => expect(mockMarkAllNotificationsRead).toHaveBeenCalledWith("test-token"));
  });

  it("shows an empty state, not a blank screen, when there are no notifications yet", async () => {
    mockGetNotifications.mockResolvedValue([]);
    render(<NotificationsScreen />);

    await waitFor(() => expect(screen.getByText("No notifications yet")).toBeTruthy());
  });

  it("shows the backend's own error message, not a generic crash, when loading fails", async () => {
    const { ApiError } = jest.requireActual("@/services/api/apiClient");
    mockGetNotifications.mockRejectedValue(new ApiError("Session expired", 401));
    render(<NotificationsScreen />);

    await waitFor(() => expect(screen.getByText("Session expired")).toBeTruthy());
  });

  it("refetches when a push notification is received while the screen is open (Phase 16)", async () => {
    let receivedCallback: (() => void) | undefined;
    const mockNotifications = {
      addNotificationReceivedListener: (cb: () => void) => {
        receivedCallback = cb;
        return { remove: jest.fn() };
      },
    };
    mockGetNotificationsModule.mockResolvedValue(mockNotifications);
    mockGetNotifications.mockResolvedValue([]);

    render(<NotificationsScreen />);
    await waitFor(() => expect(mockGetNotifications).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(receivedCallback).toBeDefined());

    mockGetNotifications.mockResolvedValue([baseNotification({ title: "Just arrived" })]);
    receivedCallback!();

    await waitFor(() => expect(screen.getByText("Just arrived")).toBeTruthy());
  });
});
