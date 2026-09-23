import Constants from "expo-constants";
import type { LocationObject } from "expo-location";

import { updateRiderLocation } from "@/services/api/riderApi";

// Background location (like expo-notifications, see
// features/notifications/push-notifications.ts) requires a real
// development/standalone build — Expo Go cannot run a background location
// task at all, and expo-task-manager itself is unreliable to even import
// there. Both modules are loaded lazily and only attempted outside Expo Go.
type TaskManagerModule = typeof import("expo-task-manager");
type LocationModule = typeof import("expo-location");

const LOCATION_TASK_NAME = "rider-background-location-task";

// Coarser than the foreground interval (12s) on purpose — a backgrounded
// app has no UI to keep fresh, and background GPS is one of the most
// battery-expensive things a phone can do. 50m/30s balances "the customer's
// map doesn't go stale for minutes" against "don't drain the rider's battery
// over an 8-hour shift."
const BACKGROUND_TIME_INTERVAL_MS = 30000;
const BACKGROUND_DISTANCE_INTERVAL_METERS = 50;

let cachedModules: { TaskManager: TaskManagerModule; Location: LocationModule } | null | undefined;
// The task callback runs outside any React tree and outside this module's
// start/stop calls, so the access token it should report with has to live
// in a plain module variable rather than a hook closure.
let currentAccessToken: string | null = null;

async function getModules() {
  if (cachedModules !== undefined) return cachedModules;

  if (Constants.appOwnership === "expo") {
    cachedModules = null;
    return cachedModules;
  }

  try {
    const [TaskManager, Location] = await Promise.all([import("expo-task-manager"), import("expo-location")]);
    cachedModules = { TaskManager, Location };
  } catch (error) {
    console.warn("Background location unavailable in this runtime:", error);
    cachedModules = null;
  }

  return cachedModules;
}

async function ensureTaskDefined(TaskManager: TaskManagerModule) {
  if (TaskManager.isTaskDefined(LOCATION_TASK_NAME)) return;

  TaskManager.defineTask(LOCATION_TASK_NAME, async ({ data, error }) => {
    if (error || !currentAccessToken) return;
    const locations = (data as { locations?: LocationObject[] } | undefined)?.locations;
    const latest = locations?.[locations.length - 1];
    if (!latest) return;

    try {
      await updateRiderLocation(currentAccessToken, latest.coords.latitude, latest.coords.longitude, {
        accuracy: latest.coords.accuracy,
        heading: latest.coords.heading,
        speed: latest.coords.speed,
      });
    } catch {
      // Best-effort — a dropped background ping isn't worth surfacing to a
      // user who likely isn't even looking at the screen.
    }
  });
}

/**
 * Starts (or is a no-op if already running) background location updates.
 * Requires foreground permission to already be granted — background
 * permission is meaningless without it — and separately requests
 * background permission itself, which on iOS surfaces the system's
 * "Change to Always Allow?" prompt. Silently does nothing if any
 * prerequisite is missing: a rider who declines background permission
 * still gets full foreground tracking (see use-location-reporter.ts) —
 * this is additive, not a hard requirement.
 */
export async function startBackgroundLocationTracking(accessToken: string): Promise<void> {
  currentAccessToken = accessToken;

  const modules = await getModules();
  if (!modules) return;
  const { TaskManager, Location } = modules;

  const { status: foregroundStatus } = await Location.getForegroundPermissionsAsync();
  if (foregroundStatus !== "granted") return;

  await ensureTaskDefined(TaskManager);

  const { status: existingBackgroundStatus } = await Location.getBackgroundPermissionsAsync();
  let backgroundStatus = existingBackgroundStatus;
  if (backgroundStatus !== "granted") {
    const requested = await Location.requestBackgroundPermissionsAsync();
    backgroundStatus = requested.status;
  }
  if (backgroundStatus !== "granted") return;

  const alreadyStarted = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME).catch(() => false);
  if (alreadyStarted) return;

  try {
    await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: BACKGROUND_TIME_INTERVAL_MS,
      distanceInterval: BACKGROUND_DISTANCE_INTERVAL_METERS,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: "Say Hi Chai Rider",
        notificationBody: "Sharing your location while you're online.",
      },
    });
  } catch (error) {
    console.warn("Unable to start background location tracking:", error);
  }
}

export async function stopBackgroundLocationTracking(): Promise<void> {
  currentAccessToken = null;

  const modules = await getModules();
  if (!modules) return;
  const { Location } = modules;

  try {
    const started = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
    if (started) await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME);
  } catch {
    // Best-effort.
  }
}
