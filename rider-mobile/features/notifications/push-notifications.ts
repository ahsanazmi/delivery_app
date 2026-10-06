import Constants from "expo-constants";
import * as Device from "expo-device";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { registerPushToken, unregisterPushToken } from "@/services/api/notificationsApi";

// Expo Go dropped support for remote push notifications on Android starting
// SDK 53 — even just `import * as Notifications from "expo-notifications"`
// throws synchronously there. A real development build (or a standalone/EAS
// build) doesn't have this restriction, so the whole feature is loaded
// lazily and only attempted outside Expo Go, rather than as a static
// top-level import that would crash every screen that transitively imports
// this file the moment it's opened in Expo Go.
type NotificationsModule = typeof import("expo-notifications");

let cachedModule: NotificationsModule | null | undefined;

async function getNotificationsModule(): Promise<NotificationsModule | null> {
  if (cachedModule !== undefined) return cachedModule;

  if (Constants.appOwnership === "expo") {
    // Running in Expo Go — known unsupported, don't even attempt the import.
    cachedModule = null;
    return cachedModule;
  }

  try {
    const module = await import("expo-notifications");
    // Foreground behavior — without this, a notification that arrives while
    // the app is open and focused is silently swallowed on some platforms.
    module.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
        shouldShowBanner: true,
        shouldShowList: true,
      }),
    });
    cachedModule = module;
  } catch (error) {
    console.warn("Push notifications unavailable in this runtime:", error);
    cachedModule = null;
  }

  return cachedModule;
}

// Tracked so signOut() can unregister the exact token this device registered,
// without needing to persist it separately just for that one use.
let currentDeviceToken: string | null = null;

function getEasProjectId(): string | null {
  const extra = (Constants as any)?.expoConfig?.extra;
  return extra?.eas?.projectId ?? (Constants as any)?.easConfig?.projectId ?? null;
}

// Expo Push Integration (Phase 16) — a stable per-install identifier,
// generated once and kept in SecureStore for the life of the install
// (deliberately never cleared on sign-out: it identifies the *device*,
// not the session, so a second rider signing in later on this same
// physical device is recognized server-side as "duplicate token"
// registration rather than as an unrelated new row — see Push Token
// Registration Phase 15). Lets upsert_push_token recognize a token
// rotation (both iOS and Android rotate push tokens periodically, not
// only on reinstall) as the *same* device re-registering, instead of
// leaving the old, now-dead token behind as an orphaned row.
const DEVICE_IDENTIFIER_KEY = "push-device-identifier";

function generateDeviceIdentifier(): string {
  return `${Platform.OS}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

async function getOrCreateDeviceIdentifier(): Promise<string> {
  const existing = await SecureStore.getItemAsync(DEVICE_IDENTIFIER_KEY);
  if (existing) return existing;
  const generated = generateDeviceIdentifier();
  await SecureStore.setItemAsync(DEVICE_IDENTIFIER_KEY, generated);
  return generated;
}

export async function registerForPushNotifications(accessToken: string): Promise<string | null> {
  if (!Device.isDevice) {
    // Simulators/emulators can't receive real push tokens.
    return null;
  }

  const Notifications = await getNotificationsModule();
  if (!Notifications) return null;

  // Expo Push Integration (Phase 16) — "do not request notification
  // permission repeatedly." requestPermissionsAsync() is only ever called
  // the first time (status "undetermined"); once the rider has answered
  // either way, every later call — the next login, the next app start —
  // re-checks the OS's own remembered answer via getPermissionsAsync()
  // and never re-prompts. "denied" is handled gracefully by returning
  // null below, exactly like "undetermined" ending in a denial does.
  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus === "undetermined") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") {
    return null;
  }

  if (Platform.OS === "android") {
    // Foreground Notification Behavior (Phase 28) — Android's own actual
    // platform behavior, not assumed to match iOS: a heads-up banner
    // only ever appears for a channel at IMPORTANCE_HIGH or above;
    // DEFAULT only ever adds a silent entry to the notification shade,
    // with no banner at all. HIGH here is what actually makes "a new
    // delivery push that arrives while the app is open still shows
    // something" true on Android, matching what setNotificationHandler's
    // shouldShowBanner already achieves on iOS — a rider needs to
    // actually notice a new-delivery alert in the moment, not find it
    // quietly sitting in the shade later.
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.HIGH,
    });
  }

  const projectId = getEasProjectId();
  if (!projectId) {
    // Getting a real Expo push token requires an EAS project id (set via
    // `npx eas init`, landing in app.json's `extra.eas.projectId`). Without
    // one, there's nothing further we can do here — fail quietly rather than
    // crash the app over a one-time setup step.
    console.warn(
      "Push notifications: no EAS project id configured (run `npx eas init`) — skipping token registration.",
    );
    return null;
  }

  try {
    const { data: expoPushToken } = await Notifications.getExpoPushTokenAsync({ projectId });
    const deviceIdentifier = await getOrCreateDeviceIdentifier();
    await registerPushToken(accessToken, {
      token: expoPushToken,
      platform: Platform.OS as "ios" | "android",
      device_identifier: deviceIdentifier,
    });
    currentDeviceToken = expoPushToken;
    return expoPushToken;
  } catch (error) {
    console.warn("Unable to register for push notifications:", error);
    return null;
  }
}

export async function unregisterCurrentDevice(accessToken: string): Promise<void> {
  if (!currentDeviceToken) return;
  const token = currentDeviceToken;
  currentDeviceToken = null;
  try {
    await unregisterPushToken(accessToken, token);
  } catch {
    // Best-effort — a token left behind after logout is harmless; the next
    // failed push to it (DeviceNotRegistered) cleans it up server-side anyway.
  }
}

export { getNotificationsModule };
