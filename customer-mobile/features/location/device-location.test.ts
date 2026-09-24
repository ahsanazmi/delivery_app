import { Alert, Linking } from "react-native";

// Maps & Location System Phase 7 — Device Location Permission. Proves
// all five states expo-location's real permission API can produce are
// each handled distinctly, the app never throws for any of them, and
// the shared alert helper shows the right message/action per state —
// including the "Open Settings" button that's only correct for the
// permanently-denied case.

const mockHasServicesEnabledAsync = jest.fn();
const mockGetForegroundPermissionsAsync = jest.fn();
const mockRequestForegroundPermissionsAsync = jest.fn();
const mockGetCurrentPositionAsync = jest.fn();

jest.mock("expo-location", () => ({
  PermissionStatus: { GRANTED: "granted", DENIED: "denied", UNDETERMINED: "undetermined" },
  Accuracy: { Balanced: 3 },
  hasServicesEnabledAsync: (...args: unknown[]) => mockHasServicesEnabledAsync(...args),
  getForegroundPermissionsAsync: (...args: unknown[]) => mockGetForegroundPermissionsAsync(...args),
  requestForegroundPermissionsAsync: (...args: unknown[]) => mockRequestForegroundPermissionsAsync(...args),
  getCurrentPositionAsync: (...args: unknown[]) => mockGetCurrentPositionAsync(...args),
}));

import { presentDeviceLocationAlert, requestDeviceLocation } from "./device-location";

describe("requestDeviceLocation", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockHasServicesEnabledAsync.mockResolvedValue(true);
  });

  it("returns granted with real coordinates when everything is allowed", async () => {
    mockGetForegroundPermissionsAsync.mockResolvedValue({ status: "granted", granted: true, canAskAgain: true, expires: "never" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 26.068, longitude: 83.1836 } });

    const result = await requestDeviceLocation();

    expect(result).toEqual({ status: "granted", latitude: 26.068, longitude: 83.1836 });
  });

  it("prompts for permission when undetermined, and honors the prompt's own result", async () => {
    mockGetForegroundPermissionsAsync.mockResolvedValue({ status: "undetermined", granted: false, canAskAgain: true, expires: "never" });
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted", granted: true, canAskAgain: true, expires: "never" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 1, longitude: 2 } });

    const result = await requestDeviceLocation();

    expect(mockRequestForegroundPermissionsAsync).toHaveBeenCalled();
    expect(result.status).toBe("granted");
  });

  it("returns denied when the permission was refused but can still be asked again", async () => {
    mockGetForegroundPermissionsAsync.mockResolvedValue({ status: "denied", granted: false, canAskAgain: true, expires: "never" });

    const result = await requestDeviceLocation();

    expect(result).toEqual({ status: "denied" });
  });

  it("returns denied_permanently when the permission was refused and can no longer be asked again", async () => {
    mockGetForegroundPermissionsAsync.mockResolvedValue({ status: "denied", granted: false, canAskAgain: false, expires: "never" });

    const result = await requestDeviceLocation();

    expect(result).toEqual({ status: "denied_permanently" });
  });

  it("returns gps_disabled when device location services are off, without even checking app permission", async () => {
    mockHasServicesEnabledAsync.mockResolvedValue(false);

    const result = await requestDeviceLocation();

    expect(result).toEqual({ status: "gps_disabled" });
    expect(mockGetForegroundPermissionsAsync).not.toHaveBeenCalled();
  });

  it("returns unavailable, never throws, when the underlying native call rejects", async () => {
    mockGetForegroundPermissionsAsync.mockResolvedValue({ status: "granted", granted: true, canAskAgain: true, expires: "never" });
    mockGetCurrentPositionAsync.mockRejectedValue(new Error("timeout"));

    const result = await requestDeviceLocation();

    expect(result).toEqual({ status: "unavailable" });
  });

  it("never continuously tracks — only ever calls the one-shot getCurrentPositionAsync, never a watch API", async () => {
    mockGetForegroundPermissionsAsync.mockResolvedValue({ status: "granted", granted: true, canAskAgain: true, expires: "never" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 1, longitude: 2 } });

    await requestDeviceLocation();

    expect(mockGetCurrentPositionAsync).toHaveBeenCalledTimes(1);
  });
});

describe("presentDeviceLocationAlert", () => {
  beforeEach(() => {
    jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    jest.spyOn(Linking, "openSettings").mockImplementation(() => Promise.resolve());
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows a plain alert (no Settings button) for a denied-but-askable state", () => {
    presentDeviceLocationAlert({ status: "denied" });

    expect(Alert.alert).toHaveBeenCalledWith(
      "Location access needed",
      expect.stringContaining("enter your address manually"),
    );
  });

  it("shows an Open Settings action specifically for permanently-denied — the one state the app can't re-prompt for itself", () => {
    presentDeviceLocationAlert({ status: "denied_permanently" });

    const [, , buttons] = (Alert.alert as jest.Mock).mock.calls[0];
    const settingsButton = buttons.find((b: any) => b.text === "Open Settings");
    expect(settingsButton).toBeDefined();

    settingsButton.onPress();
    expect(Linking.openSettings).toHaveBeenCalled();
  });

  it("shows a distinct message for GPS/location-services being off, not the same copy as a permission denial", () => {
    presentDeviceLocationAlert({ status: "gps_disabled" });
    const [title] = (Alert.alert as jest.Mock).mock.calls[0];
    expect(title).toBe("Location services are off");
  });

  it("shows a distinct message for a generic unavailable/timeout failure", () => {
    presentDeviceLocationAlert({ status: "unavailable" });
    const [title] = (Alert.alert as jest.Mock).mock.calls[0];
    expect(title).toBe("Location unavailable");
  });
});
