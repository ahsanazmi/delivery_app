import { Alert, Linking } from "react-native";

import * as Location from "expo-location";

// Maps & Location System Phase 22 — Rider Location Permission. A single,
// one-shot foreground location fetch — NOT a hook, no watchPositionAsync.
// "For this phase: Current device location may be used for map
// display/navigation preparation. Do not build continuous background
// tracking yet." This module is exactly that: used only by the Phase 21
// delivery map to show the rider's own position as a pin, distinct from
// (and never a replacement for) the existing continuous location
// reporting this app already has (use-location-reporter.ts /
// background-location-task.ts — built earlier, under a different work
// item, before this numbered phase list existed) — this module never
// reports anywhere, it only reads a position for local display.
//
// Mirrors customer-mobile/features/location/device-location.ts's exact
// shape (same expo-location APIs, same reasoning for why they're needed
// over navigator.geolocation), adapted for a rider audience.
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
    return { status: "unavailable" };
  }
}

const NON_GRANTED_ALERTS: Record<Exclude<DeviceLocationResult["status"], "granted">, { title: string; message: string }> = {
  denied: {
    title: "Location access needed",
    message: "Allow location access to show your position on the delivery map.",
  },
  denied_permanently: {
    title: "Location access is off",
    message: "Turn on location access for this app in Settings to see your position on the delivery map.",
  },
  gps_disabled: {
    title: "Location services are off",
    message: "Turn on location services on your device to see your position on the delivery map.",
  },
  unavailable: {
    title: "Location unavailable",
    message: "We couldn't get your location right now.",
  },
};

// Every state here still leaves the map and every workflow action fully
// usable without a rider's own position pin — never a blocking prompt.
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
