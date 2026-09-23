import { Redirect, Stack, useSegments } from "expo-router";

import { useAuthStore } from "@/store/authStore";

const ONBOARDING_SCREENS = new Set(["verification", "documents", "vehicle"]);

export default function AuthLayout() {
  const status = useAuthStore((state) => state.status);
  const segments = useSegments();
  // Registration signs the rider in immediately (status flips to
  // "authenticated") before routing them to /verification — and
  // documents/vehicle must stay reachable too, both before approval (that's
  // the whole point of onboarding) and after (e.g. renewing an expired
  // license or updating a vehicle). All three are the deliberate exceptions
  // to "authenticated users skip the auth group entirely".
  const isOnboardingScreen = ONBOARDING_SCREENS.has(segments[segments.length - 1]);

  if (status === "authenticated" && !isOnboardingScreen) {
    return <Redirect href="/" />;
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="login" />
      <Stack.Screen name="register" />
      <Stack.Screen name="verification" />
      <Stack.Screen name="documents" />
      <Stack.Screen name="vehicle" />
    </Stack>
  );
}
