import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

// Maps & Location System Phase 5 — Customer Address Management. Proves
// the standalone "My addresses" list screen: renders saved addresses,
// shows an empty state, and lets a customer delete/set-default without
// touching checkout's own separate address flow.

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

const mockListAddresses = jest.fn();
const mockDeleteAddress = jest.fn();
const mockSetDefaultAddress = jest.fn();
jest.mock("@/services/api/addressesApi", () => ({
  ...jest.requireActual("@/services/api/addressesApi"),
  listAddresses: (...args: unknown[]) => mockListAddresses(...args),
  deleteAddress: (...args: unknown[]) => mockDeleteAddress(...args),
  setDefaultAddress: (...args: unknown[]) => mockSetDefaultAddress(...args),
}));

import AddressesScreen from "../addresses";

function baseAddress(overrides: Record<string, unknown> = {}) {
  return {
    id: "addr-1",
    user_id: "u1",
    label: "Home",
    recipient_name: "Ravi",
    phone: "9999999999",
    address_line: "1 Main Road",
    city: "Azamgarh",
    district: "Azamgarh",
    state: "Uttar Pradesh",
    postal_code: "276001",
    landmark: null,
    latitude: null,
    longitude: null,
    formatted_address: null,
    place_id: null,
    is_default: true,
    is_active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("Addresses screen — Customer Address Management (Phase 5)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Alert, "alert").mockImplementation((title, message, buttons) => {
      // Auto-confirm the destructive action for delete-flow tests.
      const confirm = buttons?.find((b) => b.style === "destructive");
      confirm?.onPress?.();
    });
  });

  it("Protected route: redirects to /login instead of rendering addresses for an anonymous session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null });
    render(<AddressesScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("renders every saved address with its label, recipient, and full address line", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListAddresses.mockResolvedValue([baseAddress()]);

    render(<AddressesScreen />);

    await waitFor(() => {
      expect(screen.getByText("Home")).toBeTruthy();
      expect(screen.getByText("Ravi · 9999999999")).toBeTruthy();
      expect(screen.getByText("Default")).toBeTruthy();
      expect(screen.getByText(/Azamgarh, Azamgarh, Uttar Pradesh - 276001/)).toBeTruthy();
    });
  });

  it("shows an empty state, not a blank screen, when the customer has no saved addresses", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListAddresses.mockResolvedValue([]);

    render(<AddressesScreen />);

    await waitFor(() => {
      expect(screen.getByText("No saved addresses")).toBeTruthy();
    });
  });

  it("deleting an address calls the API and refreshes the list", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListAddresses.mockResolvedValueOnce([baseAddress({ is_default: false })]).mockResolvedValueOnce([]);
    mockDeleteAddress.mockResolvedValue(undefined);

    render(<AddressesScreen />);
    await waitFor(() => expect(screen.getByText("Home")).toBeTruthy());

    fireEvent.press(screen.getByText("Delete"));

    await waitFor(() => expect(mockDeleteAddress).toHaveBeenCalledWith("test-token", "addr-1"));
    await waitFor(() => expect(mockListAddresses).toHaveBeenCalledTimes(2));
  });

  it("setting a non-default address as default calls the API and refreshes the list", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockListAddresses
      .mockResolvedValueOnce([baseAddress({ is_default: false })])
      .mockResolvedValueOnce([baseAddress({ is_default: true })]);
    mockSetDefaultAddress.mockResolvedValue(baseAddress({ is_default: true }));

    render(<AddressesScreen />);
    await waitFor(() => expect(screen.getByText("Set default")).toBeTruthy());

    fireEvent.press(screen.getByText("Set default"));

    await waitFor(() => expect(mockSetDefaultAddress).toHaveBeenCalledWith("test-token", "addr-1"));
    await waitFor(() => expect(mockListAddresses).toHaveBeenCalledTimes(2));
  });

  it("shows the backend's own error message, not a generic crash, when the address list fails to load", async () => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    const { ApiError } = jest.requireActual("@/services/api/apiClient");
    mockListAddresses.mockRejectedValue(new ApiError("Session expired", 401));

    render(<AddressesScreen />);

    await waitFor(() => {
      expect(screen.getByText("Session expired")).toBeTruthy();
    });
  });
});
