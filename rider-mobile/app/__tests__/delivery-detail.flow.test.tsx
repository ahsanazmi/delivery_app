import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "order-1" }),
  useRouter: () => ({ back: jest.fn(), replace: jest.fn(), push: jest.fn() }),
  useFocusEffect: (callback: () => void | (() => void)) => {
    const { useEffect } = require("react");
    useEffect(() => callback(), []);
  },
}));

const mockUseAuthStore = jest.fn();
jest.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector(mockUseAuthStore()),
}));

const mockGetDeliveryDetail = jest.fn();
const mockPickupDelivery = jest.fn();
jest.mock("@/services/api/deliveriesApi", () => ({
  ...jest.requireActual("@/services/api/deliveriesApi"),
  getDeliveryDetail: (...args: unknown[]) => mockGetDeliveryDetail(...args),
  pickupDelivery: (...args: unknown[]) => mockPickupDelivery(...args),
  markArrivedAtRestaurant: jest.fn(),
  startDelivery: jest.fn(),
  collectCodPayment: jest.fn(),
  completeDelivery: jest.fn(),
}));

import RiderDeliveryDetailScreen from "../(rider)/delivery/[id]";

function baseDelivery(overrides: Record<string, unknown> = {}) {
  return {
    order_id: "order-1", order_number: "SHC-0001", status: "rider_assigned",
    assignment_status: "ARRIVED_AT_RESTAURANT",
    restaurant_name: "Chai House", restaurant_phone: null, restaurant_address: "1 Main Rd",
    restaurant_latitude: null, restaurant_longitude: null,
    customer_name: "Priya", customer_phone: null,
    delivery_address_line: "22 Park Ave", delivery_city: "Town", delivery_state: null,
    delivery_postal_code: "560001", delivery_landmark: null,
    delivery_latitude: null, delivery_longitude: null, delivery_instructions: null,
    items: [], subtotal: 200, delivery_fee: 30, total: 230,
    payment_method: "cod", is_paid: false, cod_amount: "230.00",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("Rider delivery flow — delivery detail screen", () => {
  beforeEach(() => {
    mockUseAuthStore.mockReturnValue({ accessToken: "test-token" });
    mockGetDeliveryDetail.mockReset();
    mockPickupDelivery.mockReset();
  });

  it("shows the 'PICK UP ORDER' action once the rider has arrived at the restaurant, and calls pickupDelivery when pressed", async () => {
    mockGetDeliveryDetail.mockResolvedValue(baseDelivery());
    mockPickupDelivery.mockResolvedValue(baseDelivery({ status: "picked_up" }));

    render(<RiderDeliveryDetailScreen />);

    const pickupButton = await screen.findByLabelText("Confirm order picked up");
    fireEvent.press(pickupButton);

    await waitFor(() => {
      expect(mockPickupDelivery).toHaveBeenCalledWith("test-token", "order-1");
    });
  });

  it("shows the backend's own error message, not a generic crash, when the delivery fails to load", async () => {
    const err = new Error("Delivery not found");
    mockGetDeliveryDetail.mockRejectedValue(err);

    render(<RiderDeliveryDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText("Delivery not found")).toBeTruthy();
    });
  });
});
