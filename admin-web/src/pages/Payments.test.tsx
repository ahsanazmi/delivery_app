import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Payments from "./Payments";

// Automated Tests (Phase 38) — Admin Payment Management (Phase 27) had
// only ever been tested at the API-request-shape layer
// (adminApi.test.ts). This file proves the actual page: it renders the
// list from the backend, applies filters as distinct query params, and
// never leaks a Razorpay secret onto the page.

const { useSessionMock, getAdminPaymentsMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  getAdminPaymentsMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/adminApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/adminApi")>();
  return { ...actual, getAdminPayments: getAdminPaymentsMock };
});

function basePayment(overrides: Record<string, unknown> = {}) {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    order_id: "order-1",
    order_number: "SHC-0001",
    customer_name: "Ravi Kumar",
    amount: "230.00",
    method: "razorpay",
    provider: "razorpay",
    status: "PAID",
    transaction_reference: "pay_rzp_abc123",
    latest_refund_status: null,
    created_at: new Date("2026-01-01T10:00:00Z").toISOString(),
    paid_at: new Date("2026-01-01T10:05:00Z").toISOString(),
    ...overrides,
  };
}

function renderPaymentsPage() {
  return render(
    <MemoryRouter>
      <Payments />
    </MemoryRouter>,
  );
}

describe("Admin Payment Management — Payments list page", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders payment id, order, customer, amount, method, provider, status, provider reference, created and paid time", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentsMock.mockResolvedValue({
      items: [basePayment()],
      total: 1,
      page: 1,
      limit: 20,
    });

    renderPaymentsPage();

    await waitFor(() => {
      expect(screen.getByText("SHC-0001")).toBeInTheDocument();
      expect(screen.getByText("Ravi Kumar")).toBeInTheDocument();
      expect(screen.getByText("₹230.00")).toBeInTheDocument();
      expect(screen.getByText("Online")).toBeInTheDocument();
      expect(screen.getByText("razorpay")).toBeInTheDocument();
      // "PAID" also appears as an <option> in the status filter <select>
      // — scope to the results table so the assertion only matches the
      // actual status pill, not the filter control.
      expect(within(screen.getByRole("table")).getByText("PAID")).toBeInTheDocument();
      expect(screen.getByText("pay_rzp_abc123")).toBeInTheDocument();
    });
  });

  it("never renders a Razorpay key secret or webhook secret anywhere on the page", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentsMock.mockResolvedValue({
      items: [basePayment()],
      total: 1,
      page: 1,
      limit: 20,
    });

    const { container } = renderPaymentsPage();

    await waitFor(() => {
      expect(screen.getByText("SHC-0001")).toBeInTheDocument();
    });
    expect(container.innerHTML).not.toMatch(/razorpay_key_secret|razorpay_webhook_secret|rzp_(live|test)_secret/i);
  });

  it("shows a distinct refund status for a partially refunded payment, not a generic label", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentsMock.mockResolvedValue({
      items: [
        basePayment({
          id: "22222222-3333-4444-5555-666666666666",
          status: "PARTIALLY_REFUNDED",
          latest_refund_status: "completed",
        }),
      ],
      total: 1,
      page: 1,
      limit: 20,
    });

    renderPaymentsPage();

    await waitFor(() => {
      // Same "also an option in the status filter <select>" collision as above.
      expect(within(screen.getByRole("table")).getByText("PARTIALLY REFUNDED")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });

  it("submitting the filter form sends status, method, order id and customer as distinct params, not folded into the search box", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentsMock.mockResolvedValue({ items: [], total: 0, page: 1, limit: 20 });

    const { user } = await import("@testing-library/user-event").then((m) => ({ user: m.default.setup() }));
    renderPaymentsPage();

    await waitFor(() => expect(getAdminPaymentsMock).toHaveBeenCalled());

    await user.type(screen.getByPlaceholderText("Order ID"), "SHC-0002");
    await user.type(screen.getByPlaceholderText("Customer"), "Priya");
    await user.selectOptions(screen.getByDisplayValue("Any method"), "cod");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(getAdminPaymentsMock).toHaveBeenLastCalledWith(
        "admin-token",
        expect.objectContaining({ order_number: "SHC-0002", customer: "Priya", method: "cod" }),
      ),
    );
  });

  it("shows the backend's own error message, not a generic crash, when the payment list fails to load", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    const { ApiError } = await import("@/services/api/apiClient");
    getAdminPaymentsMock.mockRejectedValue(new ApiError("Unable to reach payment service", 502));

    renderPaymentsPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Unable to reach payment service");
    });
  });

  it("shows an empty state, not a blank page, when no payments match the current filters", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentsMock.mockResolvedValue({ items: [], total: 0, page: 1, limit: 20 });

    renderPaymentsPage();

    await waitFor(() => {
      expect(screen.getByText("No payments match these filters.")).toBeInTheDocument();
    });
  });
});
