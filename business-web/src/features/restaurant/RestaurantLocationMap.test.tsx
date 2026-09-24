import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Maps & Location System Phase 10 — Restaurant Location Map. Mocks
// maplibre-gl the same way MapLibre React Native was mocked for
// customer-mobile's RiderMap.test.tsx: fake Map/Marker/control classes
// that record what the component does with them, since jsdom has no
// real WebGL context to render an actual map into.

const { mapInstances, markerInstances } = vi.hoisted(() => ({
  mapInstances: [] as any[],
  markerInstances: [] as any[],
}));

vi.mock("maplibre-gl", () => {
  class FakeMarker {
    lngLat: { lng: number; lat: number };
    draggable: boolean;
    listeners: Record<string, () => void> = {};
    constructor(opts: { draggable?: boolean } = {}) {
      this.draggable = Boolean(opts.draggable);
      this.lngLat = { lng: 0, lat: 0 };
      markerInstances.push(this);
    }
    setLngLat(coords: [number, number]) {
      this.lngLat = { lng: coords[0], lat: coords[1] };
      return this;
    }
    getLngLat() {
      return this.lngLat;
    }
    addTo() {
      return this;
    }
    on(event: string, handler: () => void) {
      this.listeners[event] = handler;
      return this;
    }
  }

  class FakeMap {
    listeners: Record<string, (event: any) => void> = {};
    center: [number, number];
    constructor(opts: { center: [number, number] }) {
      this.center = opts.center;
      mapInstances.push(this);
    }
    addControl() {
      return this;
    }
    on(event: string, handler: (event: any) => void) {
      this.listeners[event] = handler;
      return this;
    }
    setCenter(center: [number, number]) {
      this.center = center;
    }
    remove() {}
  }

  return {
    default: { Map: FakeMap, Marker: FakeMarker, AttributionControl: class {}, NavigationControl: class {} },
    Map: FakeMap,
    Marker: FakeMarker,
    AttributionControl: class {},
    NavigationControl: class {},
  };
});

import { RestaurantLocationMap } from "./RestaurantLocationMap";

describe("RestaurantLocationMap (Phase 10)", () => {
  afterEach(() => {
    vi.clearAllMocks();
    mapInstances.length = 0;
    markerInstances.length = 0;
  });

  it("renders a non-draggable marker in view mode", () => {
    render(<RestaurantLocationMap latitude={26.068} longitude={83.1836} editable={false} />);

    expect(markerInstances).toHaveLength(1);
    expect(markerInstances[0].draggable).toBe(false);
    expect(markerInstances[0].getLngLat()).toEqual({ lng: 83.1836, lat: 26.068 });
  });

  it("renders a draggable marker in edit mode and reports drag moves via onLocationChange", () => {
    const onLocationChange = vi.fn();
    render(
      <RestaurantLocationMap latitude={26.068} longitude={83.1836} editable onLocationChange={onLocationChange} />,
    );

    expect(markerInstances[0].draggable).toBe(true);
    markerInstances[0].setLngLat([83.2, 26.1]);
    markerInstances[0].listeners.dragend();

    expect(onLocationChange).toHaveBeenCalledWith(26.1, 83.2);
  });

  it("reports map clicks as a new marker location in edit mode", () => {
    const onLocationChange = vi.fn();
    render(
      <RestaurantLocationMap latitude={26.068} longitude={83.1836} editable onLocationChange={onLocationChange} />,
    );

    mapInstances[0].listeners.click({ lngLat: { lng: 83.25, lat: 26.2 } });

    expect(onLocationChange).toHaveBeenCalledWith(26.2, 83.25);
  });

  it("does not wire up click-to-move in view mode", () => {
    render(<RestaurantLocationMap latitude={26.068} longitude={83.1836} editable={false} />);

    expect(mapInstances[0].listeners.click).toBeUndefined();
  });

  it("moves the marker when latitude/longitude props change externally", () => {
    const { rerender } = render(<RestaurantLocationMap latitude={26.068} longitude={83.1836} editable />);

    rerender(<RestaurantLocationMap latitude={27} longitude={84} editable />);

    expect(markerInstances[0].getLngLat()).toEqual({ lng: 84, lat: 27 });
  });
});
