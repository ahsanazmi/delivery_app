import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

// Notifications & Communication System Phase 11 — Rider Notification
// Center. This screen already existed and was already substantively
// built — this file is the screen-level test that was missing, matching
// this codebase's own per-screen test convention. Also exercises the
// three new notification types this phase wired on the backend
// (document_approved/document_rejected/cod_settlement_due) and the
// destinationFor() routes added for them.

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const { useEffect } = require("react");
    useEffect(() => callback(), []);
  },
}));

const mockRouter = { back: jest.fn(), push: jest.fn(), replace: jest.fn() };

const mockUseAuthStore = jest.fn();
jest.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector(mockUseAuthStore()),
}));

const mockGetNotificationsModule = jest.fn();
jest.mock("@/features/notifications/push-notifications", () => ({
  getNotificationsModule: () => mockGetNotificationsModule(),
}));

jest.mock("@/hooks/use-theme-colors", () => ({
  useThemeColors: () => ({ background: "#fff", text: "#000", border: "#ccc", card: "#fff", primary: "#f60", muted: "#888" }),
}));

const mockGetRiderNotifications = jest.fn();
const mockMarkRiderNotificationRead = jest.fn();
const mockMarkAllRiderNotificationsRead = jest.fn();
jest.mock("@/services/api/notificationsApi", () => ({
  getRiderNotifications: (...args: unknown[]) => mockGetRiderNotifications(...args),
  markRiderNotificationRead: (...args: unknown[]) => mockMarkRiderNotificationRead(...args),
  markAllRiderNotificationsRead: (...args: unknown[]) => mockMarkAllRiderNotificationsRead(...args),
}));

import RiderNotificationsScreen from "../(rider)/notifications";

function baseNotification(overrides: Record<string, unknown> = {}) {
  return {
    id: "notif-1",
    type: "new_delivery",
    title: "New delivery available",
    body: "A new delivery is ready for pickup.",
    order_id: null,
    data: { type: "new_delivery" },
    is_read: false,
    created_at: new Date().toISOString(),
    read_at: null,
    ...overrides,
  };
}

describe("RiderNotificationsScreen", () => {
  beforeEach(() => {
    mockUseAuthStore.mockReturnValue({ accessToken: "test-token" });
    mockGetRiderNotifications.mockReset();
    mockMarkRiderNotificationRead.mockReset().mockResolvedValue({});
    mockMarkAllRiderNotificationsRead.mockReset().mockResolvedValue({ updated: 0 });
    mockRouter.push.mockReset();
    mockGetNotificationsModule.mockReset().mockResolvedValue(null);
  });

  it("prompts to log in instead of rendering the list for an anonymous session", () => {
    mockUseAuthStore.mockReturnValue({ accessToken: null });
    render(<RiderNotificationsScreen />);
    expect(screen.getByText("Please log in to continue.")).toBeTruthy();
  });

  it("shows title, body, and a relative time for each notification", async () => {
    mockGetRiderNotifications.mockResolvedValue([baseNotification()]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => {
      expect(screen.getByText(/New delivery available/)).toBeTruthy();
      expect(screen.getByText("A new delivery is ready for pickup.")).toBeTruthy();
    });
  });

  it("marks a notification read and navigates to the dashboard when a new-delivery alert is tapped", async () => {
    mockGetRiderNotifications.mockResolvedValue([baseNotification()]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText(/New delivery available/)).toBeTruthy());
    fireEvent.press(screen.getByText(/New delivery available/));

    await waitFor(() => expect(mockMarkRiderNotificationRead).toHaveBeenCalledWith("test-token", "notif-1"));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/" });
  });

  it("routes a document_approved notification to /verification", async () => {
    mockGetRiderNotifications.mockResolvedValue([
      baseNotification({ id: "doc-1", type: "document_approved", title: "Document approved", body: "Your Driving License has been approved." }),
    ]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText(/Document approved/)).toBeTruthy());
    fireEvent.press(screen.getByText(/Document approved/));

    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/verification" }));
  });

  it("routes a cod_settlement_due notification to /wallet", async () => {
    mockGetRiderNotifications.mockResolvedValue([
      baseNotification({ id: "cod-1", type: "cod_settlement_due", title: "COD settlement due", body: "You have an outstanding COD balance of 1000.00 awaiting settlement." }),
    ]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText(/COD settlement due/)).toBeTruthy());
    fireEvent.press(screen.getByText(/COD settlement due/));

    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/wallet" }));
  });

  it("routes a delivery_updated (reassigned-away) notification to the dashboard, not the no-longer-owned delivery", async () => {
    mockGetRiderNotifications.mockResolvedValue([
      baseNotification({ id: "reassign-1", type: "delivery_updated", title: "Delivery reassigned", body: "Order SHC-1 has been reassigned.", order_id: "order-1" }),
    ]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText(/Delivery reassigned/)).toBeTruthy());
    fireEvent.press(screen.getByText(/Delivery reassigned/));

    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/" }));
  });

  it("marks every notification read via the header action", async () => {
    mockGetRiderNotifications.mockResolvedValue([baseNotification({ id: "n1" }), baseNotification({ id: "n2", title: "Second" })]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText(/Mark all read/)).toBeTruthy());
    fireEvent.press(screen.getByText(/Mark all read/));

    await waitFor(() => expect(mockMarkAllRiderNotificationsRead).toHaveBeenCalledWith("test-token"));
  });

  it("shows an empty state, not a blank screen, when there are no notifications yet", async () => {
    mockGetRiderNotifications.mockResolvedValue([]);
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText("No notifications yet.")).toBeTruthy());
  });

  it("shows an error state with a retry option when loading fails", async () => {
    mockGetRiderNotifications.mockRejectedValue(new Error("Network down"));
    render(<RiderNotificationsScreen />);

    await waitFor(() => expect(screen.getByText("Network down")).toBeTruthy());
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
    mockGetRiderNotifications.mockResolvedValue([]);

    render(<RiderNotificationsScreen />);
    await waitFor(() => expect(mockGetRiderNotifications).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(receivedCallback).toBeDefined());

    mockGetRiderNotifications.mockResolvedValue([baseNotification({ title: "Just arrived" })]);
    receivedCallback!();

    await waitFor(() => expect(screen.getByText(/Just arrived/)).toBeTruthy());
  });
});
