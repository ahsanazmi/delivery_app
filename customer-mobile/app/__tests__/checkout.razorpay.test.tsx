import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

// Customer Mobile Razorpay Checkout (Phase 13) — proves the mandated
// 7-step flow end to end at the UI layer: request initialization, receive
// checkout information, open Razorpay checkout, receive the result, send
// it to backend verification, refetch payment status independently, and
// only then display the final result — never trusting the mobile callback
// alone.

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: mockReplace }),
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

jest.mock("@/services/api/addressesApi", () => ({
  createAddress: jest.fn(),
}));

const mockGetCheckout = jest.fn();
const mockValidateOrder = jest.fn();
jest.mock("@/services/api/checkoutApi", () => ({
  getCheckout: (...args: unknown[]) => mockGetCheckout(...args),
  validateOrder: (...args: unknown[]) => mockValidateOrder(...args),
}));

const mockCreateOrder = jest.fn();
jest.mock("@/services/api/ordersApi", () => ({
  createOrder: (...args: unknown[]) => mockCreateOrder(...args),
}));

const mockGetPaymentMethods = jest.fn();
const mockRecordOrderPayment = jest.fn();
const mockVerifyPayment = jest.fn();
const mockGetPaymentRecord = jest.fn();
jest.mock("@/services/api/paymentsApi", () => ({
  getPaymentMethods: (...args: unknown[]) => mockGetPaymentMethods(...args),
  recordOrderPayment: (...args: unknown[]) => mockRecordOrderPayment(...args),
  verifyPayment: (...args: unknown[]) => mockVerifyPayment(...args),
  getPaymentRecord: (...args: unknown[]) => mockGetPaymentRecord(...args),
}));

const mockReplace = jest.fn();

import CheckoutScreen from "../checkout";

const baseCheckout = {
  addresses: [{ id: "addr-1", label: "Home", recipient_name: "Ravi", is_default: true, address_line: "1 Main", city: "BLR", state: "KA" }],
  selected_address: { id: "addr-1", label: "Home", recipient_name: "Ravi", is_default: true, address_line: "1 Main", city: "BLR", state: "KA" },
  restaurant: { id: "r1", name: "Chai House" },
  items: [{ id: "i1", product_name: "Dosa", unit_price: 100, quantity: 1 }],
  subtotal: 100, delivery_fee: 30, tax: 0, discount: 0, total: 130,
  total_items: 1, removed_items: [], coupon_code: null, coupon_message: null, issues: [],
};

describe("Checkout — Razorpay online payment (Phase 13)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSession.mockReturnValue({
      user: { id: "u1", name: "Ravi", email: "ravi@example.com", phone: "9999999999" },
      accessToken: "test-token",
    });
    mockGetCheckout.mockResolvedValue(baseCheckout);
    mockGetPaymentMethods.mockResolvedValue([
      { method: "cod", label: "Cash on Delivery", available: true },
      { method: "online", label: "Pay Online", available: true },
    ]);
    mockValidateOrder.mockResolvedValue({ valid: true, issues: [] });
    jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  });

  it("offers an online payment option when the backend reports it available", async () => {
    render(<CheckoutScreen />);
    await waitFor(() => expect(screen.getByText("Pay Online")).toBeTruthy());
  });

  it("does not offer online payment when the backend reports it unavailable", async () => {
    mockGetPaymentMethods.mockResolvedValue([
      { method: "cod", label: "Cash on Delivery", available: true },
      { method: "online", label: "Pay Online", available: false },
    ]);
    render(<CheckoutScreen />);
    await waitFor(() => expect(screen.getByText("Cash on Delivery")).toBeTruthy());
    const onlineRow = screen.getByText("Pay Online");
    expect(onlineRow).toBeTruthy();
    // Selecting it must not switch the payment method — Currently unavailable stays shown.
    fireEvent.press(onlineRow);
    expect(screen.getByText("Currently unavailable")).toBeTruthy();
  });

  it("full success path: creates the order, opens Razorpay, verifies, refetches, and reports success", async () => {
    mockCreateOrder.mockResolvedValue({ id: "order-1", total: 130 });
    mockRecordOrderPayment.mockResolvedValue({
      payment_id: "pay-1", order_id: "order-1", amount: 130, method: "online",
      status: "pending", transaction_reference: "order_rzp_1", razorpay_key_id: "rzp_test_abc",
      created_at: "", updated_at: "",
    });
    mockOpen.mockResolvedValue({
      razorpay_payment_id: "pay_rzp_1", razorpay_order_id: "order_rzp_1", razorpay_signature: "sig123",
    });
    mockVerifyPayment.mockResolvedValue({ id: "pay-1", status: "paid" });
    mockGetPaymentRecord.mockResolvedValue({ id: "pay-1", status: "paid" });

    render(<CheckoutScreen />);
    await waitFor(() => expect(screen.getByText("Pay Online")).toBeTruthy());
    fireEvent.press(screen.getByText("Pay Online"));
    fireEvent.press(screen.getByText(/Place order/));

    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalledWith(
      "test-token",
      expect.objectContaining({ payment_method: "razorpay" }),
    ));
    await waitFor(() => expect(mockOpen).toHaveBeenCalledWith(
      expect.objectContaining({ key: "rzp_test_abc", order_id: "order_rzp_1", amount: 13000, currency: "INR" }),
    ));
    await waitFor(() => expect(mockVerifyPayment).toHaveBeenCalledWith(
      "test-token", "pay-1",
      { provider_order_id: "order_rzp_1", provider_payment_id: "pay_rzp_1", signature: "sig123" },
    ));
    // Step 6 — an independent refetch happens after verify, not a reuse of verify's own response.
    await waitFor(() => expect(mockGetPaymentRecord).toHaveBeenCalledWith("test-token", "pay-1"));
    await waitFor(() => expect(Alert.alert).toHaveBeenCalledWith("Payment successful", expect.any(String)));
    expect(mockReplace).toHaveBeenCalledWith("/orders");
  });

  it("never treats a verified-but-not-yet-confirmed callback as success without the refetch agreeing", async () => {
    mockCreateOrder.mockResolvedValue({ id: "order-1", total: 130 });
    mockRecordOrderPayment.mockResolvedValue({
      payment_id: "pay-1", order_id: "order-1", amount: 130, method: "online",
      status: "pending", transaction_reference: "order_rzp_1", razorpay_key_id: "rzp_test_abc",
      created_at: "", updated_at: "",
    });
    mockOpen.mockResolvedValue({
      razorpay_payment_id: "pay_rzp_1", razorpay_order_id: "order_rzp_1", razorpay_signature: "sig123",
    });
    mockVerifyPayment.mockResolvedValue({ id: "pay-1", status: "paid" });
    // The independent refetch disagrees with verify()'s own optimistic response — this must win.
    mockGetPaymentRecord.mockResolvedValue({ id: "pay-1", status: "failed" });

    render(<CheckoutScreen />);
    await waitFor(() => expect(screen.getByText("Pay Online")).toBeTruthy());
    fireEvent.press(screen.getByText("Pay Online"));
    fireEvent.press(screen.getByText(/Place order/));

    await waitFor(() => expect(mockGetPaymentRecord).toHaveBeenCalled());
    await waitFor(() => expect(Alert.alert).toHaveBeenCalledWith("Payment not completed", expect.any(String)));
  });

  it("a cancelled/failed Razorpay checkout never calls verify, and reports failure", async () => {
    mockCreateOrder.mockResolvedValue({ id: "order-1", total: 130 });
    mockRecordOrderPayment.mockResolvedValue({
      payment_id: "pay-1", order_id: "order-1", amount: 130, method: "online",
      status: "pending", transaction_reference: "order_rzp_1", razorpay_key_id: "rzp_test_abc",
      created_at: "", updated_at: "",
    });
    mockOpen.mockRejectedValue({ code: 2, description: "Payment cancelled by user" });

    render(<CheckoutScreen />);
    await waitFor(() => expect(screen.getByText("Pay Online")).toBeTruthy());
    fireEvent.press(screen.getByText("Pay Online"));
    fireEvent.press(screen.getByText(/Place order/));

    await waitFor(() => expect(mockOpen).toHaveBeenCalled());
    expect(mockVerifyPayment).not.toHaveBeenCalled();
    expect(mockGetPaymentRecord).not.toHaveBeenCalled();
    await waitFor(() => expect(Alert.alert).toHaveBeenCalledWith("Payment not completed", expect.any(String)));
  });

  it("the COD path never touches Razorpay at all", async () => {
    mockCreateOrder.mockResolvedValue({ id: "order-1", total: 130 });
    mockRecordOrderPayment.mockResolvedValue({
      payment_id: "pay-1", order_id: "order-1", amount: 130, method: "cod",
      status: "pending", transaction_reference: null, razorpay_key_id: null,
      created_at: "", updated_at: "",
    });

    render(<CheckoutScreen />);
    await waitFor(() => expect(screen.getByText("Cash on Delivery")).toBeTruthy());
    fireEvent.press(screen.getByText(/Place order/));

    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalledWith(
      "test-token",
      expect.objectContaining({ payment_method: "cod" }),
    ));
    expect(mockOpen).not.toHaveBeenCalled();
    expect(mockVerifyPayment).not.toHaveBeenCalled();
  });
});
