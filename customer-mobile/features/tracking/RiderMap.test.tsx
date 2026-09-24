import { render, screen, waitFor } from "@testing-library/react-native";

// Live Rider Location Tracking — MapLibre's native components can't
// render in Jest (no native host), so this mocks them the same way
// this codebase already mocks react-native-razorpay elsewhere: plain
// View stand-ins that still receive real props, so behavior around
// *which* markers render, and that the camera is actually told to
// re-center on a fresh rider position (not MapLibre's own internals),
// stays covered.
const mockEaseTo = jest.fn();
jest.mock("@maplibre/maplibre-react-native", () => {
  const { forwardRef, useImperativeHandle } = require("react");
  const { View } = require("react-native");
  return {
    Map: ({ children, testID, ...props }: any) => (
      <View testID="maplibre-map" {...props}>
        {children}
      </View>
    ),
    Camera: forwardRef((_props: any, ref: any) => {
      useImperativeHandle(ref, () => ({ easeTo: mockEaseTo, jumpTo: jest.fn(), flyTo: jest.fn() }));
      return null;
    }),
    Marker: ({ id, children }: any) => <View testID={`marker-${id}`}>{children}</View>,
  };
});

import { RiderMap } from "./RiderMap";

describe("RiderMap — Live Rider Location Tracking", () => {
  beforeEach(() => {
    mockEaseTo.mockReset();
  });

  it("shows a waiting placeholder, not a blank/crashed map, when no location is known yet", () => {
    render(<RiderMap riderLocation={null} deliveryLocation={null} />);
    expect(screen.getByText(/Waiting for the rider's location/)).toBeTruthy();
    expect(screen.queryByTestId("maplibre-map")).toBeNull();
  });

  it("renders the map with a rider marker once a location arrives", () => {
    render(
      <RiderMap
        riderLocation={{ latitude: 26.068, longitude: 83.1836 }}
        deliveryLocation={null}
      />,
    );
    expect(screen.getByTestId("maplibre-map")).toBeTruthy();
    expect(screen.getByTestId("marker-rider")).toBeTruthy();
    expect(screen.queryByTestId("marker-delivery")).toBeNull();
  });

  it("also renders a distinct delivery marker when the destination is known", () => {
    render(
      <RiderMap
        riderLocation={{ latitude: 26.068, longitude: 83.1836 }}
        deliveryLocation={{ latitude: 26.07, longitude: 83.19 }}
      />,
    );
    expect(screen.getByTestId("marker-rider")).toBeTruthy();
    expect(screen.getByTestId("marker-delivery")).toBeTruthy();
  });

  it("still renders the map centered on the destination even before the rider has reported a position", () => {
    render(
      <RiderMap
        riderLocation={null}
        deliveryLocation={{ latitude: 26.07, longitude: 83.19 }}
      />,
    );
    expect(screen.getByTestId("maplibre-map")).toBeTruthy();
    expect(screen.queryByTestId("marker-rider")).toBeNull();
    expect(screen.getByTestId("marker-delivery")).toBeTruthy();
  });

  it("eases the camera to the rider's new position whenever a fresh location arrives — the actual 'moving marker without refreshing' mechanism", async () => {
    const { rerender } = render(
      <RiderMap riderLocation={{ latitude: 26.068, longitude: 83.1836 }} deliveryLocation={null} />,
    );
    await waitFor(() =>
      expect(mockEaseTo).toHaveBeenLastCalledWith(expect.objectContaining({ center: [83.1836, 26.068] })),
    );

    rerender(<RiderMap riderLocation={{ latitude: 26.07, longitude: 83.19 }} deliveryLocation={null} />);

    await waitFor(() =>
      expect(mockEaseTo).toHaveBeenLastCalledWith(expect.objectContaining({ center: [83.19, 26.07] })),
    );
  });

  it("shows the required CARTO/OpenStreetMap attribution whenever the map itself renders", () => {
    render(
      <RiderMap
        riderLocation={{ latitude: 26.068, longitude: 83.1836 }}
        deliveryLocation={null}
      />,
    );
    expect(screen.getByText(/OpenStreetMap/)).toBeTruthy();
  });
});
