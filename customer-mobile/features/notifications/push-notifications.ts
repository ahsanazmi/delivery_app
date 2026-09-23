import Constants from "expo-constants";
import * as Device from "expo-device";
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

export async function registerForPushNotifications(accessToken: string): Promise<string | null> {
  if (!Device.isDevice) {
    // Simulators/emulators can't receive real push tokens.
    return null;
  }

  const Notifications = await getNotificationsModule();
  if (!Notifications) return null;

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") {
    return null;
  }

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.DEFAULT,
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
    await registerPushToken(accessToken, { token: expoPushToken, platform: Platform.OS as "ios" | "android" });
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
