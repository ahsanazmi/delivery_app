import { Redirect, Stack } from "expo-router";

import { useBackgroundLocationTracking } from "@/features/location/use-background-location";
import { useLocationReporter } from "@/features/location/use-location-reporter";
import { useTrackingEligibility } from "@/features/location/use-tracking-eligibility";
import { useAuthStore } from "@/store/authStore";

export default function RiderLayout() {
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);
  const accessToken = useAuthStore((state) => state.accessToken);

  // Mounted exactly once here, above every rider screen, so a rider who is
  // both online and mid-delivery gets exactly one reporting interval instead
  // of one per screen that cares about their position. Phase 22's rule —
  // "only transmit when ONLINE or has an active delivery" — is entirely
  // captured by shouldTrackLocation; neither hook below has any further
  // opinion on when to run.
  const shouldTrackLocation = useTrackingEligibility(status === "authenticated" ? accessToken : null);
  useLocationReporter(status === "authenticated" ? accessToken : null, shouldTrackLocation);
  useBackgroundLocationTracking(status === "authenticated" ? accessToken : null, shouldTrackLocation);

  // Client-side guard only, for UX (skip straight to login instead of a
  // flash of empty screens) — the real authorization is enforced by every
  // backend endpoint via require_rider(), which checks the user's actual
  // stored role. A Customer/Restaurant Owner/Admin could delete this whole
  // file and still get 403s from every /api/v1/rider/* call.
  //
  // Unlike an earlier version of this file, a rider who isn't APPROVED yet
  // is *not* redirected away from here — Phase 6 draws the line at specific
  // actions ("cannot go online", "cannot accept deliveries"), not at
  // entering the app at all. The home screen shows the rider's account
  // status and disables the online toggle itself; the backend enforces the
  // same rule independently via set_rider_online_status().
  if (status !== "authenticated" || user?.role !== "RIDER") {
    return <Redirect href="/login" />;
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="delivery/[id]" />
      <Stack.Screen name="profile" />
    </Stack>
  );
}
