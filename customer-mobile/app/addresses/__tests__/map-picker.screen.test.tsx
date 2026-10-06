import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";

// Maps & Location System Phase 8 — proves the map picker's "Confirm
// location" flow: a successful reverse geocode hands the full address
// to place-search-context; a null/failed reverse geocode still
// confirms the bare coordinate via location-picker-context (Phase 6's
// original behavior), never blocking the confirm action either way.
//
// Rebuilt on MapLibre Native (dropping react-native-maps/Google) — see
// map-picker.tsx's own comment for why. Mocks @maplibre/maplibre-react-
// native the same way RiderMap.test.tsx does; MapLibre's Marker has no
// drag support, so this picker uses a fixed center-screen pin with the
// map panning underneath it (onRegionDidChange) instead of a draggable
// marker — the mock's Map component exposes those same event props so
// that mechanic is directly testable too.

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: mockBack, push: jest.fn(), replace: jest.fn() }),
}));

const mockBack = jest.fn();
const mockEaseTo = jest.fn();

jest.mock("@maplibre/maplibre-react-native", () => {
  const { forwardRef, useImperativeHandle } = require("react");
  const { View } = require("react-native");
  return {
    Map: ({ children, onPress, onRegionDidChange, ...props }: any) => (
      <View testID="maplibre-map" onPress={onPress} onRegionDidChange={onRegionDidChange} {...props}>
        {children}
      </View>
    ),
    Camera: forwardRef((_props: any, ref: any) => {
      useImperativeHandle(ref, () => ({ easeTo: mockEaseTo, jumpTo: jest.fn(), flyTo: jest.fn() }));
      return null;
    }),
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

  it("tapping the map eases the camera to the tapped coordinate, rather than placing a draggable marker", () => {
    render(<MapPickerScreen />);
    fireEvent(screen.getByTestId("maplibre-map"), "press", { nativeEvent: { lngLat: [83.2, 26.1] } });

    expect(mockEaseTo).toHaveBeenCalledWith(expect.objectContaining({ center: [83.2, 26.1] }));
  });

  it("confirms whatever coordinate the map last settled on after panning (onRegionDidChange), not the original center", async () => {
    mockReverseGeocode.mockResolvedValue({ result: null });
    render(<MapPickerScreen />);

    fireEvent(screen.getByTestId("maplibre-map"), "regionDidChange", {
      nativeEvent: { center: [83.25, 26.15] },
    });
    fireEvent.press(screen.getByText("Confirm location"));

    await waitFor(() => expect(mockSetPickedLocation).toHaveBeenCalledWith({ latitude: 26.15, longitude: 83.25 }));
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
