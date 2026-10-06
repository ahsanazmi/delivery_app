import { render, screen } from "@testing-library/react-native";

// Maps & Location System Phase 19 — same MapLibre mocking pattern as
// features/tracking/RiderMap.test.tsx (MapLibre's native components
// can't render in Jest).
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

import { DeliveryLocationPreview } from "./DeliveryLocationPreview";

describe("DeliveryLocationPreview — Checkout Location Integration (Phase 19)", () => {
  it("renders the map with a single delivery-location marker", () => {
    render(<DeliveryLocationPreview latitude={26.068} longitude={83.1836} distanceKm={null} />);
    expect(screen.getByTestId("maplibre-map")).toBeTruthy();
    expect(screen.getByTestId("marker-delivery-location")).toBeTruthy();
  });

  it("shows the distance when one is provided", () => {
    render(<DeliveryLocationPreview latitude={26.068} longitude={83.1836} distanceKm={4.3} />);
    expect(screen.getByText(/4\.3 km from the restaurant/)).toBeTruthy();
  });

  it("shows no distance text when distanceKm is null — informational only, never required", () => {
    render(<DeliveryLocationPreview latitude={26.068} longitude={83.1836} distanceKm={null} />);
    expect(screen.queryByText(/km from the restaurant/)).toBeNull();
  });

  it("shows the required CARTO/OpenStreetMap attribution", () => {
    render(<DeliveryLocationPreview latitude={26.068} longitude={83.1836} distanceKm={null} />);
    expect(screen.getByText(/OpenStreetMap/)).toBeTruthy();
  });
});
