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

const mockListPaymentHistory = jest.fn();
jest.mock("@/services/api/paymentsApi", () => ({
  ...jest.requireActual("@/services/api/paymentsApi"),
  listPaymentHistory: (...args: unknown[]) => mockListPaymentHistory(...args),
}));

import PaymentHistoryScreen from "../payments";

function basePayment(overrides: Record<string, unknown> = {}) {
  return {
    payment_id: "pay-1",
    order_id: "order-1",
    order_number: "SHC-0001",
    amount: 230,
    method: "cod",
    status: "paid",
    transaction_reference: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("Payment history screen — customer payment history (Phase 26)", () => {
  beforeEach(() => {
    mockListPaymentHistory.mockReset();
  });

  it("Protected route: redirects to /login instead of rendering payment history for an anonymous session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null });
    render(<PaymentHistoryScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("renders the payment's order number, amount, method, and status once loaded", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListPaymentHistory.mockResolvedValue([basePayment()]);

    render(<PaymentHistoryScreen />);

    await waitFor(() => {
      expect(screen.getByText("SHC-0001")).toBeTruthy();
      expect(screen.getByText("₹230")).toBeTruthy();
      expect(screen.getByText("Cash on delivery")).toBeTruthy();
      expect(screen.getByText("Paid")).toBeTruthy();
    });
  });

  it("renders an online payment distinctly from a COD one", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListPaymentHistory.mockResolvedValue([
      basePayment({ payment_id: "pay-2", method: "online", status: "pending" }),
    ]);

    render(<PaymentHistoryScreen />);

    await waitFor(() => {
      expect(screen.getByText("Paid online")).toBeTruthy();
      expect(screen.getByText("Payment pending")).toBeTruthy();
    });
  });

  it("shows an empty state, not a blank screen, when the customer has no payments yet", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListPaymentHistory.mockResolvedValue([]);

    render(<PaymentHistoryScreen />);

    await waitFor(() => {
      expect(screen.getByText("No payments yet")).toBeTruthy();
    });
  });

  it("shows the backend's own error message, not a generic crash, when the payment history fails to load", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    const { ApiError } = jest.requireActual("@/services/api/apiClient");
    mockListPaymentHistory.mockRejectedValue(new ApiError("Session expired", 401));

    render(<PaymentHistoryScreen />);

    await waitFor(() => {
      expect(screen.getByText("Session expired")).toBeTruthy();
    });
  });
});
