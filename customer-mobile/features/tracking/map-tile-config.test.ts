// Live Rider Location Tracking — proves the tile-provider config is
// genuinely swappable via one env var, and that a real attribution
// string is always present (required by both CARTO's and OpenStreetMap's
// terms regardless of which style URL ends up configured).

describe("map-tile-config", () => {
  const ORIGINAL_ENV = process.env.EXPO_PUBLIC_MAP_STYLE_URL;

  afterEach(() => {
    process.env.EXPO_PUBLIC_MAP_STYLE_URL = ORIGINAL_ENV;
    jest.resetModules();
  });

  it("falls back to the documented default CARTO style when no env override is set", () => {
    delete process.env.EXPO_PUBLIC_MAP_STYLE_URL;
    jest.resetModules();
    const { MAP_STYLE_URL, DEFAULT_MAP_STYLE_URL } = require("./map-tile-config");
    expect(MAP_STYLE_URL).toBe(DEFAULT_MAP_STYLE_URL);
    expect(MAP_STYLE_URL).toMatch(/^https:\/\//);
  });

  it("uses a configured style URL instead of the default when one is set — this is the whole point of separating the library from the provider", () => {
    process.env.EXPO_PUBLIC_MAP_STYLE_URL = "https://tiles.example.com/my-style.json";
    jest.resetModules();
    const { MAP_STYLE_URL } = require("./map-tile-config");
    expect(MAP_STYLE_URL).toBe("https://tiles.example.com/my-style.json");
  });

  it("ignores a blank/whitespace-only override and falls back to the default", () => {
    process.env.EXPO_PUBLIC_MAP_STYLE_URL = "   ";
    jest.resetModules();
    const { MAP_STYLE_URL, DEFAULT_MAP_STYLE_URL } = require("./map-tile-config");
    expect(MAP_STYLE_URL).toBe(DEFAULT_MAP_STYLE_URL);
  });

  it("always exports a real attribution string, required regardless of provider", () => {
    jest.resetModules();
    const { MAP_ATTRIBUTION_TEXT } = require("./map-tile-config");
    expect(MAP_ATTRIBUTION_TEXT.length).toBeGreaterThan(0);
    expect(MAP_ATTRIBUTION_TEXT).toMatch(/OpenStreetMap/);
  });
});
