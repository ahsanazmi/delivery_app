import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

// Maps & Location System Phase 8 — proves the map picker's "Confirm
// location" flow: a successful reverse geocode hands the full address
// to place-search-context; a null/failed reverse geocode still
// confirms the bare coordinate via location-picker-context (Phase 6's
// original behavior), never blocking the confirm action either way.

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: mockBack, push: jest.fn(), replace: jest.fn() }),
}));

const mockBack = jest.fn();

jest.mock("react-native-maps", () => {
  const { View } = require("react-native");
  const MockMapView = ({ children, ...props }: any) => <View testID="map-view" {...props}>{children}</View>;
  const MockMarker = (props: any) => <View testID="marker" {...props} />;
  return {
    __esModule: true,
    default: MockMapView,
    Marker: MockMarker,
    PROVIDER_GOOGLE: "google",
  };
});

jest.mock("@/features/location/device-location", () => ({
  requestDeviceLocation: jest.fn().mockResolvedValue({ status: "denied" }),
}));

const mockSetPickedLocation = jest.fn();
jest.mock("@/features/addresses/location-picker-context", () => ({
  useLocationPicker: () => ({ pickedLocation: null, setPickedLocation: mockSetPickedLocation }),
}));

const mockSetPickedPlace = jest.fn();
jest.mock("@/features/addresses/place-search-context", () => ({
  usePickedPlace: () => ({ pickedPlace: null, setPickedPlace: mockSetPickedPlace }),
}));

const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

const mockReverseGeocode = jest.fn();
jest.mock("@/services/api/locationSearchApi", () => ({
  reverseGeocode: (...args: unknown[]) => mockReverseGeocode(...args),
}));

import MapPickerScreen from "../map-picker";

describe("Map picker — Reverse Geocoding on confirm (Phase 8)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSession.mockReturnValue({ accessToken: "test-token" });
  });

  it("a successful reverse geocode hands the full place to place-search-context, not just the coordinate", async () => {
    const place = {
      label: "Azamgarh, Uttar Pradesh", address_line: null, city: "Azamgarh", district: null,
      state: "Uttar Pradesh", postal_code: "276001", country: "India",
      latitude: 26.068, longitude: 83.1836,
      formatted_address: "Azamgarh, Uttar Pradesh, India", place_id: "N:765060153",
    };
    mockReverseGeocode.mockResolvedValue({ result: place });

    render(<MapPickerScreen />);
    fireEvent.press(screen.getByText("Confirm location"));

    await waitFor(() => expect(mockSetPickedPlace).toHaveBeenCalledWith(place));
    expect(mockSetPickedLocation).not.toHaveBeenCalled();
    expect(mockBack).toHaveBeenCalled();
  });

  it("falls back to the bare coordinate when nothing is found at the pin — still confirms, never blocks", async () => {
    mockReverseGeocode.mockResolvedValue({ result: null });

    render(<MapPickerScreen />);
    fireEvent.press(screen.getByText("Confirm location"));

    await waitFor(() => expect(mockSetPickedLocation).toHaveBeenCalled());
    expect(mockSetPickedPlace).not.toHaveBeenCalled();
    expect(mockBack).toHaveBeenCalled();
  });

  it("falls back to the bare coordinate when reverse geocoding itself fails — still confirms, never crashes", async () => {
    mockReverseGeocode.mockRejectedValue(new Error("network error"));

    render(<MapPickerScreen />);
    fireEvent.press(screen.getByText("Confirm location"));

    await waitFor(() => expect(mockSetPickedLocation).toHaveBeenCalled());
    expect(mockBack).toHaveBeenCalled();
  });

  it("confirms the bare coordinate directly, with no reverse-geocode call at all, when there's no session yet", async () => {
    mockUseSession.mockReturnValue({ accessToken: null });

    render(<MapPickerScreen />);
    fireEvent.press(screen.getByText("Confirm location"));

    await waitFor(() => expect(mockSetPickedLocation).toHaveBeenCalled());
    expect(mockReverseGeocode).not.toHaveBeenCalled();
  });
});
