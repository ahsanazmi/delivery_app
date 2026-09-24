import { Alert, Linking } from "react-native";

import * as Location from "expo-location";

// Maps & Location System Phase 7 — Device Location Permission.
//
// A single, one-shot location fetch — NOT a hook, no watchPositionAsync,
// no background task. This module is used only from screens that need
// "where is the customer right now, once" (checkout's "use my location"
// button, the Phase 6 map picker's initial centering) — continuous
// customer tracking is explicitly out of scope for this whole module.
//
// expo-location (not the raw navigator.geolocation polyfill both
// checkout.tsx and map-picker.tsx used before this phase) is what makes
// the five states below distinguishable at all — navigator.geolocation's
// error callback only ever reports a generic PERMISSION_DENIED/
// POSITION_UNAVAILABLE/TIMEOUT code, with no way to tell "denied, can
// ask again" from "denied permanently, must go to Settings" the way
// expo-location's own `canAskAgain` flag can.
export type DeviceLocationResult =
  | { status: "granted"; latitude: number; longitude: number }
  | { status: "denied" }
  | { status: "denied_permanently" }
  | { status: "gps_disabled" }
  | { status: "unavailable" };

export async function requestDeviceLocation(): Promise<DeviceLocationResult> {
  try {
    const servicesEnabled = await Location.hasServicesEnabledAsync();
    if (!servicesEnabled) {
      return { status: "gps_disabled" };
    }

    let permission = await Location.getForegroundPermissionsAsync();
    if (permission.status === Location.PermissionStatus.UNDETERMINED) {
      permission = await Location.requestForegroundPermissionsAsync();
    }

    if (permission.status !== Location.PermissionStatus.GRANTED) {
      return permission.canAskAgain ? { status: "denied" } : { status: "denied_permanently" };
    }

    const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return { status: "granted", latitude: position.coords.latitude, longitude: position.coords.longitude };
  } catch {
    // A real device/GPS/timeout failure that isn't a permission or
    // services-disabled case (both already handled above) — the app
    // must never crash here, only report "we don't have it right now".
    return { status: "unavailable" };
  }
}

const NON_GRANTED_ALERTS: Record<
  Exclude<DeviceLocationResult["status"], "granted">,
  { title: string; message: string }
> = {
  denied: {
    title: "Location access needed",
    message: "Allow location access to use your current position, or enter your address manually.",
  },
  denied_permanently: {
    title: "Location access is off",
    message: "Turn on location access for this app in Settings, or enter your address manually.",
  },
  gps_disabled: {
    title: "Location services are off",
    message: "Turn on location services on your device, or enter your address manually.",
  },
  unavailable: {
    title: "Location unavailable",
    message: "We couldn't get your location right now. Please enter your address manually.",
  },
};

// Shared so checkout.tsx, the map picker, and any future screen show the
// exact same message per state instead of drifting apart — every one of
// these must leave manual entry / the map picker / a saved address as a
// live option; none of them ever exit or trap the customer.
export function presentDeviceLocationAlert(result: Exclude<DeviceLocationResult, { status: "granted" }>): void {
  const copy = NON_GRANTED_ALERTS[result.status];
  if (result.status === "denied_permanently") {
    Alert.alert(copy.title, copy.message, [
      { text: "Not now", style: "cancel" },
      { text: "Open Settings", onPress: () => Linking.openSettings() },
    ]);
    return;
  }
  Alert.alert(copy.title, copy.message);
}
