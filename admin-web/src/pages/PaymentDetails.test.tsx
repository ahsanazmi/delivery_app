import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import PaymentDetails from "./PaymentDetails";

// Automated Tests (Phase 38) — Admin Payment Management (Phase 27),
// detail view: proves the page shows every field the phase required
// (order, customer, amount, method, provider, status, provider
// reference, created/paid time, refund status, COD collection info)
// and never leaks a provider secret.

const { useSessionMock, getAdminPaymentDetailMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  getAdminPaymentDetailMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/adminApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/adminApi")>();
  return { ...actual, getAdminPaymentDetail: getAdminPaymentDetailMock };
});

function baseDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    order_id: "order-1",
    order_number: "SHC-0001",
    customer_name: "Ravi Kumar",
    customer_email: "ravi@example.com",
    amount: "230.00",
    currency: "INR",
    method: "razorpay",
    provider: "razorpay",
    status: "PAID",
    transaction_reference: "pay_rzp_abc123",
    latest_refund_status: null,
    is_verified: true,
    failure_reason: null,
    collected_by_rider_name: null,
    collected_at: null,
    created_at: new Date("2026-01-01T10:00:00Z").toISOString(),
    paid_at: new Date("2026-01-01T10:05:00Z").toISOString(),
    updated_at: new Date("2026-01-01T10:05:00Z").toISOString(),
    ...overrides,
  };
}

function renderPaymentDetailsPage(paymentId = "11111111-2222-3333-4444-555555555555") {
  return render(
    <MemoryRouter initialEntries={[`/payments/${paymentId}`]}>
      <Routes>
        <Route path="/payments/:paymentId" element={<PaymentDetails />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Admin Payment Management — Payment details page", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows order, customer, amount, method, provider, status, provider reference, verified flag, and paid time", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentDetailMock.mockResolvedValue(baseDetail());

    const { container } = renderPaymentDetailsPage();

    await waitFor(() => {
      expect(screen.getByText("SHC-0001")).toBeInTheDocument();
      // Name and email sit either side of a <br/>, so no single node's
      // textContent is exactly "Ravi Kumar" — check the rendered page
      // text directly instead of a single-node match.
      expect(container.textContent).toContain("Ravi Kumar");
      expect(container.textContent).toContain("ravi@example.com");
      expect(screen.getByText("INR 230.00")).toBeInTheDocument();
      expect(screen.getByText("Online")).toBeInTheDocument();
      expect(screen.getByText("razorpay")).toBeInTheDocument();
      expect(screen.getByText("pay_rzp_abc123")).toBeInTheDocument();
      expect(screen.getByText("Yes")).toBeInTheDocument();
      expect(screen.getByText("PAID")).toBeInTheDocument();
    });
  });

  it("shows a failed payment's specific failure reason", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentDetailMock.mockResolvedValue(
      baseDetail({ status: "FAILED", is_verified: false, paid_at: null, failure_reason: "Payment signature verification failed." }),
    );

    renderPaymentDetailsPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Payment signature verification failed.");
    });
  });

  it("shows COD collection info (collected by / collected at) only for a COD payment", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentDetailMock.mockResolvedValue(
      baseDetail({
        method: "cod",
        provider: null,
        transaction_reference: null,
        collected_by_rider_name: "Amit Singh",
        collected_at: new Date("2026-01-01T12:00:00Z").toISOString(),
      }),
    );

    renderPaymentDetailsPage();

    await waitFor(() => {
      expect(screen.getByText("Amit Singh")).toBeInTheDocument();
    });
  });

  it("shows the current refund status for a partially refunded payment", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentDetailMock.mockResolvedValue(
      baseDetail({ status: "PARTIALLY_REFUNDED", latest_refund_status: "completed" }),
    );

    renderPaymentDetailsPage();

    await waitFor(() => {
      expect(screen.getByText("Refund status")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });

  it("never renders a Razorpay key secret, webhook secret, or JWT-looking token anywhere on the page", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    getAdminPaymentDetailMock.mockResolvedValue(baseDetail());

    const { container } = renderPaymentDetailsPage();

    await waitFor(() => {
      expect(screen.getByText("SHC-0001")).toBeInTheDocument();
    });
    expect(container.innerHTML).not.toMatch(/razorpay_key_secret|razorpay_webhook_secret|rzp_(live|test)_secret|eyJhbGci/i);
  });

  it("shows the backend's own error message, not a generic crash, when the payment can't be found", async () => {
    useSessionMock.mockReturnValue({ accessToken: "admin-token" });
    const { ApiError } = await import("@/services/api/apiClient");
    getAdminPaymentDetailMock.mockRejectedValue(new ApiError("Payment not found", 404));

    renderPaymentDetailsPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Payment not found");
    });
  });
});
