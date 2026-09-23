import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

// Payment Failure Handling (Phase 19) — proves the order detail screen
// shows a clear state per payment outcome (paid / failed with a reason /
// pending / no payment record yet) and that "Retry Payment" /
// "Complete Payment" always reuses the SAME order — never places a
// second one — regardless of which state it started from.

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "order-1" }),
  useFocusEffect: (callback: () => void | (() => void)) => {
    const { useEffect } = require("react");
    useEffect(() => callback(), []);
  },
}));

const mockOpen = jest.fn();
jest.mock("react-native-razorpay", () => ({
  __esModule: true,
  default: { open: (...args: unknown[]) => mockOpen(...args) },
}));

const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

jest.mock("@/features/cart/cart-context", () => ({
  useCart: () => ({ refresh: jest.fn() }),
}));

const mockGetOrder = jest.fn();
jest.mock("@/services/api/ordersApi", () => ({
  ...jest.requireActual("@/services/api/ordersApi"),
  getOrder: (...args: unknown[]) => mockGetOrder(...args),
}));

const mockGetPaymentByOrder = jest.fn();
const mockRecordOrderPayment = jest.fn();
const mockRetryPayment = jest.fn();
const mockVerifyPayment = jest.fn();
const mockGetPaymentRecord = jest.fn();
jest.mock("@/services/api/paymentsApi", () => ({
  getPaymentByOrder: (...args: unknown[]) => mockGetPaymentByOrder(...args),
  recordOrderPayment: (...args: unknown[]) => mockRecordOrderPayment(...args),
  retryPayment: (...args: unknown[]) => mockRetryPayment(...args),
  verifyPayment: (...args: unknown[]) => mockVerifyPayment(...args),
  getPaymentRecord: (...args: unknown[]) => mockGetPaymentRecord(...args),
}));

import OrderDetailScreen from "../orders/[id]";

function baseOrder(overrides: Record<string, unknown> = {}) {
  return {
    id: "order-1", user_id: "u1", rider_id: null, customer_name: "Ravi",
    customer_email: "ravi@example.com", customer_phone: null,
    restaurant_id: "r1", restaurant_name: "Chai House", restaurant_phone: null, restaurant_address: null,
    order_number: "SHC-0001", status: "placed", payment_method: "razorpay",
    subtotal: 200, delivery_fee: 30, tax: 0, discount: 0, total: 230, item_count: 1,
    address_line: "1 Main", city: "BLR", state: "KA", postal_code: "560001",
    landmark: null, latitude: null, longitude: null, delivery_instructions: null, cancelled_reason: null,
    payment_status: "pending", is_paid: false, items: [], status_history: [],
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("Order detail — payment failure handling (Phase 19)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSession.mockReturnValue({
      user: { id: "u1", name: "Ravi", email: "ravi@example.com", phone: "9999999999" },
      accessToken: "test-token",
    });
    jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  });

  it("shows a clear 'Payment Failed' state with the specific reason", async () => {
    mockGetOrder.mockResolvedValue(baseOrder());
    mockGetPaymentByOrder.mockResolvedValue({
      id: "pay-1", order_id: "order-1", method: "razorpay", status: "failed",
      amount: 230, currency: "INR", provider_order_id: "order_rzp_1", provider_payment_id: null,
      is_verified: false, paid_at: null, created_at: "", updated_at: "",
      razorpay_key_id: "rzp_test_abc", failure_reason: "Payment signature verification failed.",
    });

    render(<OrderDetailScreen />);

    await waitFor(() => expect(screen.getByText("Payment failed")).toBeTruthy());
    expect(screen.getByText("Payment signature verification failed.")).toBeTruthy();
    expect(screen.getByText("Retry Payment")).toBeTruthy();
  });

  it("shows 'Payment pending' with a 'Complete Payment' action, not 'Retry'", async () => {
    mockGetOrder.mockResolvedValue(baseOrder());
    mockGetPaymentByOrder.mockResolvedValue({
      id: "pay-2", order_id: "order-1", method: "razorpay", status: "pending",
      amount: 230, currency: "INR", provider_order_id: "order_rzp_2", provider_payment_id: null,
      is_verified: false, paid_at: null, created_at: "", updated_at: "",
      razorpay_key_id: "rzp_test_abc", failure_reason: null,
    });

    render(<OrderDetailScreen />);

    await waitFor(() => expect(screen.getByText("Payment pending")).toBeTruthy());
    expect(screen.getByText("Complete Payment")).toBeTruthy();
    expect(screen.queryByText("Retry Payment")).toBeNull();
  });

  it("shows 'Payment not started' with no payment record, and starting one never creates a second order", async () => {
    mockGetOrder.mockResolvedValue(baseOrder());
    mockGetPaymentByOrder.mockRejectedValue(new Error("404"));
    mockRecordOrderPayment.mockResolvedValue({
      payment_id: "pay-3", order_id: "order-1", amount: 230, method: "online", status: "pending",
      transaction_reference: "order_rzp_3", razorpay_key_id: "rzp_test_abc", created_at: "", updated_at: "",
    });
    mockOpen.mockResolvedValue({ razorpay_payment_id: "pay_x", razorpay_order_id: "order_rzp_3", razorpay_signature: "sig" });
    mockVerifyPayment.mockResolvedValue({});
    mockGetPaymentRecord.mockResolvedValue({ status: "paid", failure_reason: null });

    render(<OrderDetailScreen />);
    await waitFor(() => expect(screen.getByText("Payment not started")).toBeTruthy());

    fireEvent.press(screen.getByText("Complete Payment"));

    await waitFor(() => expect(mockRecordOrderPayment).toHaveBeenCalledWith("test-token", "order-1"));
    // The SAME order id is reused — no createOrder call happens from this screen at all.
    expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ order_id: "order_rzp_3" }));
  });

  it("retrying a failed payment calls /retry before reopening checkout, reusing the same provider order", async () => {
    mockGetOrder.mockResolvedValue(baseOrder());
    mockGetPaymentByOrder.mockResolvedValue({
      id: "pay-4", order_id: "order-1", method: "razorpay", status: "failed",
      amount: 230, currency: "INR", provider_order_id: "order_rzp_4", provider_payment_id: null,
      is_verified: false, paid_at: null, created_at: "", updated_at: "",
      razorpay_key_id: "rzp_test_abc", failure_reason: "Payment signature verification failed.",
    });
    mockRetryPayment.mockResolvedValue({
      id: "pay-4", order_id: "order-1", method: "razorpay", status: "pending",
      amount: 230, currency: "INR", provider_order_id: "order_rzp_4", provider_payment_id: null,
      is_verified: false, paid_at: null, created_at: "", updated_at: "",
      razorpay_key_id: "rzp_test_abc", failure_reason: null,
    });
    mockOpen.mockResolvedValue({ razorpay_payment_id: "pay_y", razorpay_order_id: "order_rzp_4", razorpay_signature: "sig" });
    mockVerifyPayment.mockResolvedValue({});
    mockGetPaymentRecord.mockResolvedValue({ status: "paid", failure_reason: null });

    render(<OrderDetailScreen />);
    await waitFor(() => expect(screen.getByText("Retry Payment")).toBeTruthy());

    fireEvent.press(screen.getByText("Retry Payment"));

    await waitFor(() => expect(mockRetryPayment).toHaveBeenCalledWith("test-token", "pay-4"));
    await waitFor(() => expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ order_id: "order_rzp_4" })));
    expect(mockRecordOrderPayment).not.toHaveBeenCalled();
  });

  it("an already-paid payment shows 'Paid' with no retry button at all", async () => {
    mockGetOrder.mockResolvedValue(baseOrder({ payment_status: "paid", is_paid: true }));
    mockGetPaymentByOrder.mockResolvedValue({
      id: "pay-5", order_id: "order-1", method: "razorpay", status: "paid",
      amount: 230, currency: "INR", provider_order_id: "order_rzp_5", provider_payment_id: "pay_z",
      is_verified: true, paid_at: new Date().toISOString(), created_at: "", updated_at: "",
      razorpay_key_id: "rzp_test_abc", failure_reason: null,
    });

    render(<OrderDetailScreen />);

    await waitFor(() => expect(screen.getAllByText("Paid").length).toBeGreaterThan(0));
    expect(screen.queryByText("Retry Payment")).toBeNull();
    expect(screen.queryByText("Complete Payment")).toBeNull();
  });
});
