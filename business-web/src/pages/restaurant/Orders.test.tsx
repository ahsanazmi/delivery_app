import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import OrdersPage from "./Orders";

const { useSessionMock, listRestaurantOrdersMock } = vi.hoisted(() => ({
  useSessionMock: vi.fn(),
  listRestaurantOrdersMock: vi.fn(),
}));

vi.mock("@/features/auth/session-context", () => ({
  useSession: useSessionMock,
}));

vi.mock("@/services/api/ordersApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api/ordersApi")>();
  return { ...actual, listRestaurantOrders: listRestaurantOrdersMock };
});

function renderOrdersPage() {
  return render(
    <MemoryRouter>
      <OrdersPage />
    </MemoryRouter>,
  );
}

describe("Restaurant order management — Orders page", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the incoming orders list from the API, masked customer name and all", () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    listRestaurantOrdersMock.mockResolvedValue([
      {
        id: "order-1", order_number: "SHC-0001", customer_name_masked: "R*** K.",
        item_count: 2, total: "310.00", payment_method: "cod", payment_status: "pending", status: "placed",
        created_at: new Date().toISOString(),
        restaurant_earning: "280.00", commission: "28.00", net_amount: "252.00",
      },
    ]);

    renderOrdersPage();

    return waitFor(() => {
      expect(screen.getByText(/New Order #SHC-0001/)).toBeInTheDocument();
      expect(screen.getByText(/R\*\*\* K\./)).toBeInTheDocument();
      expect(screen.getByText(/1 NEW/)).toBeInTheDocument();
      expect(screen.getByText(/Net: ₹252\.00/)).toBeInTheDocument();
      expect(screen.getByText(/COD · pending/)).toBeInTheDocument();
    });
  });

  it("shows the backend's own error message, not a generic crash, when the order list fails to load", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    const { ApiError } = await import("@/services/api/apiClient");
    listRestaurantOrdersMock.mockRejectedValue(new ApiError("Restaurant not found", 404));

    renderOrdersPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Restaurant not found");
    });
  });

  it("shows an empty state, not a blank page, when there are no orders in the current view", async () => {
    useSessionMock.mockReturnValue({ accessToken: "test-token" });
    listRestaurantOrdersMock.mockResolvedValue([]);

    renderOrdersPage();

    await waitFor(() => {
      expect(screen.getByText("No orders in this view.")).toBeInTheDocument();
    });
  });
});
