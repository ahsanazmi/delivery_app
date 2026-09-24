import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Maps & Location System Phase 11 — mocks maplibre-gl the same way
// business-web's RestaurantLocationMap.test.tsx does: fake Map/Marker
// classes recording what the component does with them, since jsdom has
// no real WebGL context.

const { mapInstances, markerInstances } = vi.hoisted(() => ({
  mapInstances: [] as any[],
  markerInstances: [] as any[],
}));

vi.mock("maplibre-gl", () => {
  class FakeMarker {
    lngLat: { lng: number; lat: number };
    draggable: boolean;
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
  }

  class FakeMap {
    center: [number, number];
    constructor(opts: { center: [number, number] }) {
      this.center = opts.center;
      mapInstances.push(this);
    }
    addControl() {
      return this;
    }
    on() {
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

import { LocationMap } from "./LocationMap";

describe("LocationMap (Phase 11)", () => {
  afterEach(() => {
    vi.clearAllMocks();
    mapInstances.length = 0;
    markerInstances.length = 0;
  });

  it("renders a non-draggable marker at the given coordinates", () => {
    render(<LocationMap latitude={26.068} longitude={83.1836} />);

    expect(markerInstances).toHaveLength(1);
    expect(markerInstances[0].draggable).toBe(false);
    expect(markerInstances[0].getLngLat()).toEqual({ lng: 83.1836, lat: 26.068 });
  });

  it("moves the marker and re-centers when coordinates change externally", () => {
    const { rerender } = render(<LocationMap latitude={26.068} longitude={83.1836} />);

    rerender(<LocationMap latitude={27} longitude={84} />);

    expect(markerInstances[0].getLngLat()).toEqual({ lng: 84, lat: 27 });
    expect(mapInstances[0].center).toEqual([84, 27]);
  });
});
