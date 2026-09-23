import { render, screen, waitFor } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (callback: () => void | (() => void)) => {
    const { useEffect } = require("react");
    useEffect(() => callback(), []);
  },
}));

const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

jest.mock("@/features/cart/cart-context", () => ({
  useCart: () => ({ refresh: jest.fn() }),
}));

const mockListOrders = jest.fn();
jest.mock("@/services/api/ordersApi", () => ({
  ...jest.requireActual("@/services/api/ordersApi"),
  listOrders: (...args: unknown[]) => mockListOrders(...args),
  reorderOrder: jest.fn(),
}));

import OrdersScreen from "../orders";

function baseOrder(overrides: Record<string, unknown> = {}) {
  return {
    id: "order-1", user_id: "u1", rider_id: null, customer_name: "Ravi",
    customer_email: "ravi@example.com", customer_phone: null,
    restaurant_id: "r1", restaurant_name: "Chai House", restaurant_phone: null, restaurant_address: null,
    order_number: "SHC-0001", status: "placed", payment_method: "cod",
    subtotal: 200, delivery_fee: 30, total: 230, item_count: 2, items: [],
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("Order screens — customer order list", () => {
  beforeEach(() => {
    mockListOrders.mockReset();
  });

  it("Protected route: redirects to /login instead of rendering orders for an anonymous session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null });
    render(<OrdersScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("renders the order's number, restaurant, and status once loaded for a logged-in customer", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListOrders.mockResolvedValue([baseOrder()]);

    render(<OrdersScreen />);

    await waitFor(() => {
      expect(screen.getByText("SHC-0001")).toBeTruthy();
      expect(screen.getByText("Chai House")).toBeTruthy();
    });
  });

  it("shows an empty state, not a blank screen, when the customer has no orders yet", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListOrders.mockResolvedValue([]);

    render(<OrdersScreen />);

    await waitFor(() => {
      expect(screen.getByText("No orders yet")).toBeTruthy();
    });
  });

  it("shows the backend's own error message, not a generic crash, when the order list fails to load", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    const { ApiError } = jest.requireActual("@/services/api/apiClient");
    mockListOrders.mockRejectedValue(new ApiError("Session expired", 401));

    render(<OrdersScreen />);

    await waitFor(() => {
      expect(screen.getByText("Session expired")).toBeTruthy();
    });
  });
});
