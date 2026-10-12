import {
    createContext,
    PropsWithChildren,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";

import { useSession } from "@/features/auth/session-context";
import {
    presentDeviceLocationAlert,
    requestDeviceLocation,
} from "@/features/location/device-location";
import { listAddresses, type Address } from "@/services/api/addressesApi";

// The point restaurant discovery is filtered to: the backend only returns
// restaurants whose delivery radius covers it, nearest first. Resolved once
// here and shared, so home, the restaurant list, categories and search all
// agree on "where am I ordering to".
export type DeliveryLocation = {
  latitude: number;
  longitude: number;
  label: string;
  source: "address" | "device";
};

type DeliveryLocationStatus = "loading" | "ready" | "none";

type DeliveryLocationContextValue = {
  location: DeliveryLocation | null;
  status: DeliveryLocationStatus;
  /** Re-reads the default address (e.g. after the customer adds one), without a loading state. */
  refresh: () => Promise<void>;
  /** Explicit "use my current location" tap — shows the permission alert on failure. */
  requestCurrentLocation: () => Promise<void>;
};

const DeliveryLocationContext = createContext<DeliveryLocationContextValue | null>(null);

function fromAddress(address: Address): DeliveryLocation | null {
  if (address.latitude == null || address.longitude == null) return null;
  return {
    latitude: Number(address.latitude),
    longitude: Number(address.longitude),
    label: `${address.label}, ${address.city}`,
    source: "address",
  };
}

function sameLocation(a: DeliveryLocation | null, b: DeliveryLocation | null) {
  return a?.latitude === b?.latitude && a?.longitude === b?.longitude && a?.label === b?.label;
}

export function DeliveryLocationProvider({ children }: PropsWithChildren) {
  const { accessToken } = useSession();
  const [location, setLocationState] = useState<DeliveryLocation | null>(null);
  const [status, setStatus] = useState<DeliveryLocationStatus>("loading");

  // Keeps the same object when nothing changed, so screens depending on
  // `location` don't refetch restaurants on a no-op refresh.
  const setLocation = useCallback((next: DeliveryLocation | null) => {
    setLocationState((current) => (sameLocation(current, next) ? current : next));
  }, []);

  const resolve = useCallback(async (silent = false) => {
    if (!silent) setStatus("loading");
    if (accessToken) {
      try {
        const addresses = await listAddresses(accessToken);
        const preferred = addresses.find((address) => address.is_default) ?? addresses[0];
        const fromSaved = preferred ? fromAddress(preferred) : null;
        if (fromSaved) {
          setLocation(fromSaved);
          setStatus("ready");
          return;
        }
      } catch {
        // Fall through to device location — a failed address fetch must
        // never leave the customer with no restaurants at all.
      }
    }
    const device = await requestDeviceLocation();
    if (device.status === "granted") {
      setLocation({ latitude: device.latitude, longitude: device.longitude, label: "Current location", source: "device" });
      setStatus("ready");
    } else {
      setLocation(null);
      setStatus("none");
    }
  }, [accessToken, setLocation]);

  useEffect(() => {
    void resolve();
  }, [resolve]);

  const refresh = useCallback(() => resolve(true), [resolve]);

  const requestCurrentLocation = useCallback(async () => {
    setStatus("loading");
    const device = await requestDeviceLocation();
    if (device.status === "granted") {
      setLocation({ latitude: device.latitude, longitude: device.longitude, label: "Current location", source: "device" });
      setStatus("ready");
      return;
    }
    presentDeviceLocationAlert(device);
    setStatus(location ? "ready" : "none");
  }, [location, setLocation]);

  const value = useMemo<DeliveryLocationContextValue>(
    () => ({ location, status, refresh, requestCurrentLocation }),
    [location, status, refresh, requestCurrentLocation],
  );

  return <DeliveryLocationContext.Provider value={value}>{children}</DeliveryLocationContext.Provider>;
}

export function useDeliveryLocation() {
  const context = useContext(DeliveryLocationContext);
  if (!context) throw new Error("useDeliveryLocation must be used inside DeliveryLocationProvider");
  return context;
}

/** Query params for discovery endpoints; empty when no location is known. */
export function locationParams(location: DeliveryLocation | null) {
  return location ? { latitude: location.latitude, longitude: location.longitude } : {};
}
