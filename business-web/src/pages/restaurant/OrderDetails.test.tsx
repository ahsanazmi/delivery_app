import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import OrderDetailsPage from "./OrderDetails";

const { useSessionMock, getRestaurantOrderMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  getRestaurantOrderMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/ordersApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/ordersApi")>();
  return { ...actual, getRestaurantOrder: getRestaurantOrderMock };
});

function baseOrder(overrides: Record<string, unknown> = {}) {
  return {
    id: "order-1", user_id: "u1", rider_id: null,
    customer_name: "Ravi Kumar", customer_email: "ravi@example.com", customer_phone: "9999999999",
    restaurant_id: "r1", restaurant_name: "Diner", restaurant_phone: null, restaurant_address: null,
    order_number: "SHC-0001", status: "placed", payment_method: "razorpay",
    subtotal: "280.00", delivery_fee: "30.00", tax: "0.00", discount: "0.00", total: "310.00",
    item_count: 1, address_line: "1 Road", city: "Town", state: null, postal_code: "123456",
    landmark: null, latitude: null, longitude: null, delivery_instructions: null, cancelled_reason: null,
    payment_status: "paid", is_paid: true,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    items: [], status_history: [],
    restaurant_earning: "280.00", commission: "28.00", net_amount: "252.00",
    ...overrides,
  };
}

function renderOrderDetailsPage() {
  return render(
    <MemoryRouter initialEntries={["/orders/order-1"]}>
      <Routes>
        <Route path="/orders/:orderId" element={<OrderDetailsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Restaurant order management — Order details page — Restaurant Payment Visibility (Phase 28)", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows order amount, restaurant earning, commission, net amount, payment method, and payment status", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    getRestaurantOrderMock.mockResolvedValue(baseOrder());

    renderOrderDetailsPage();

    await waitFor(() => {
      expect(screen.getByText("Your earnings")).toBeInTheDocument();
      expect(screen.getByText("RAZORPAY · paid")).toBeInTheDocument();
      expect(screen.getByText("₹252.00")).toBeInTheDocument(); // Net amount
      expect(screen.getByText("-₹28.00")).toBeInTheDocument(); // Commission
    });
  });

  it("never renders any Razorpay signature or provider-secret-looking text", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    getRestaurantOrderMock.mockResolvedValue(baseOrder());

    const { container } = renderOrderDetailsPage();

    await waitFor(() => {
      expect(screen.getByText("Your earnings")).toBeInTheDocument();
    });
    expect(container.innerHTML).not.toMatch(/razorpay_signature|razorpay_key_secret/i);
  });
});
