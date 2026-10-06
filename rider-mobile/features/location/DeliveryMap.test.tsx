import { render, screen } from "@testing-library/react-native";

// Maps & Location System Phase 21 — Rider Map Foundation. Same MapLibre
// mocking pattern as customer-mobile/features/tracking/RiderMap.test.tsx.
jest.mock("@maplibre/maplibre-react-native", () => {
  const { View } = require("react-native");
  return {
    Map: ({ children, ...props }: any) => (
      <View testID="maplibre-map" {...props}>
        {children}
      </View>
    ),
    Camera: () => null,
    Marker: ({ id, children }: any) => <View testID={`marker-${id}`}>{children}</View>,
  };
});

import { DeliveryMap } from "./DeliveryMap";

const RIDER = { latitude: 26.068, longitude: 83.1836 };
const RESTAURANT = { latitude: 26.07, longitude: 83.19 };
const CUSTOMER = { latitude: 26.08, longitude: 83.2 };

describe("DeliveryMap — Rider Map Foundation (Phase 21)", () => {
  it("shows a placeholder, not a blank/crashed map, when no location is known at all", () => {
    render(<DeliveryMap currentLocation={null} restaurantLocation={null} customerLocation={null} />);
    expect(screen.getByText(/No location available yet/)).toBeTruthy();
    expect(screen.queryByTestId("maplibre-map")).toBeNull();
  });

  it("renders all three pins when every location is known", () => {
    render(<DeliveryMap currentLocation={RIDER} restaurantLocation={RESTAURANT} customerLocation={CUSTOMER} />);
    expect(screen.getByTestId("maplibre-map")).toBeTruthy();
    expect(screen.getByTestId("marker-rider")).toBeTruthy();
    expect(screen.getByTestId("marker-restaurant")).toBeTruthy();
    expect(screen.getByTestId("marker-customer")).toBeTruthy();
  });

  it("still renders the map centered on the restaurant when the rider's own position isn't known — never blocks on it", () => {
    render(<DeliveryMap currentLocation={null} restaurantLocation={RESTAURANT} customerLocation={CUSTOMER} />);
    expect(screen.getByTestId("maplibre-map")).toBeTruthy();
    expect(screen.queryByTestId("marker-rider")).toBeNull();
    expect(screen.getByTestId("marker-restaurant")).toBeTruthy();
  });

  it("omits the customer marker when the delivery has no pinned coordinates", () => {
    render(<DeliveryMap currentLocation={RIDER} restaurantLocation={RESTAURANT} customerLocation={null} />);
    expect(screen.queryByTestId("marker-customer")).toBeNull();
  });

  it("shows a legend distinguishing you/restaurant/customer, and the required attribution", () => {
    render(<DeliveryMap currentLocation={RIDER} restaurantLocation={RESTAURANT} customerLocation={CUSTOMER} />);
    expect(screen.getByText("You")).toBeTruthy();
    expect(screen.getByText("Restaurant")).toBeTruthy();
    expect(screen.getByText("Customer")).toBeTruthy();
    expect(screen.getByText(/OpenStreetMap/)).toBeTruthy();
  });
});
