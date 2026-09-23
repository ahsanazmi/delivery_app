import { Linking } from "react-native";

/**
 * A clean abstraction over "open turn-by-turn directions to somewhere" so the
 * app never talks to a specific maps provider directly from a screen.
 *
 * Today this is implemented with a keyless deep link that hands off to
 * whatever maps app is installed (Google Maps on Android, falling back to
 * the browser) — no origin is specified, so the maps app resolves "current
 * location" itself, exactly matching "Current Location -> Restaurant".
 *
 * This deliberately does NOT call the Google Maps Directions/Places API,
 * which would require an API key. A mobile app bundle can be decompiled by
 * anyone who installs it, so an API key embedded here would be public the
 * moment the app ships — there is no way to keep a client-side secret
 * secret. When richer navigation (in-app turn-by-turn, live ETAs, route
 * previews) is needed later, that has to go through the backend: the
 * mobile app calls our own API, and the backend — which nobody can
 * decompile — holds the real Google Maps API key and proxies the request.
 * Swapping in that provider only means implementing NavigationProvider
 * again; every screen that calls navigateToRestaurant()/navigateToAddress()
 * stays unchanged.
 */

export type Coordinates = {
  latitude: number;
  longitude: number;
};

export type NavigationDestination = {
  /** Shown in error messages / analytics, not sent to the maps app. */
  label: string;
  coordinates?: Coordinates | null;
  /** Used when coordinates aren't available yet (e.g. a restaurant with no lat/long on file). */
  address?: string | null;
};

export interface NavigationProvider {
  openDirections(destination: NavigationDestination): Promise<void>;
}

function destinationQuery(destination: NavigationDestination): string | null {
  if (destination.coordinates) {
    return `${destination.coordinates.latitude},${destination.coordinates.longitude}`;
  }
  if (destination.address && destination.address.trim()) {
    return encodeURIComponent(destination.address.trim());
  }
  return null;
}

/** Keyless deep link — works with any device maps app, today's default provider. */
class DeviceMapsNavigationProvider implements NavigationProvider {
  async openDirections(destination: NavigationDestination): Promise<void> {
    const query = destinationQuery(destination);
    if (!query) {
      throw new Error(`No location available to navigate to for ${destination.label}.`);
    }
    // No "origin" parameter on purpose — every major maps app treats a
    // directions link with no origin as "start from where I am right now".
    const url = `https://www.google.com/maps/dir/?api=1&destination=${query}`;
    const canOpen = await Linking.canOpenURL(url);
    if (!canOpen) {
      throw new Error("No app available to open directions.");
    }
    await Linking.openURL(url);
  }
}

// The one place a future GoogleMapsSdkNavigationProvider (backed by the
// backend proxy described above) would get swapped in.
export const navigationProvider: NavigationProvider = new DeviceMapsNavigationProvider();

export function navigateTo(destination: NavigationDestination): Promise<void> {
  return navigationProvider.openDirections(destination);
}
