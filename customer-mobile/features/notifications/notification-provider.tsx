import { useRouter } from "expo-router";
import { PropsWithChildren, useEffect } from "react";

import { useSession } from "@/features/auth/session-context";
import { getNotificationsModule, registerForPushNotifications } from "./push-notifications";

type AppRouter = ReturnType<typeof useRouter>;

function handleDeepLink(router: AppRouter, data: Record<string, unknown> | undefined) {
  if (!data) return;
  if (data.type === "order_status" && typeof data.order_id === "string") {
    router.push({ pathname: "/track/[id]", params: { id: data.order_id } });
  } else if (data.type === "promotion") {
    router.push("/home");
  }
}

/**
 * Renders nothing — just wires up push-notification lifecycle for the whole
 * app: registering (and re-registering on token refresh) while signed in,
 * and deep-linking a tapped notification to the right screen, both for a
 * cold start (app launched by tapping one) and while already running.
 *
 * No-ops entirely in Expo Go (see push-notifications.ts) — `expo-notifications`
 * is loaded lazily there, so this provider never touches the real module
 * unless it's actually available in the current runtime.
 */
export function NotificationProvider({ children }: PropsWithChildren) {
  const { accessToken } = useSession();
  const router = useRouter();

  useEffect(() => {
    let responseSubscription: { remove: () => void } | undefined;
    let cancelled = false;

    void getNotificationsModule().then((Notifications) => {
      if (!Notifications || cancelled) return;

      responseSubscription = Notifications.addNotificationResponseReceivedListener((response) => {
        handleDeepLink(router, response.notification.request.content.data as Record<string, unknown>);
      });

      void Notifications.getLastNotificationResponseAsync().then((response) => {
        if (response) {
          handleDeepLink(router, response.notification.request.content.data as Record<string, unknown>);
        }
      });
    });

    return () => {
      cancelled = true;
      responseSubscription?.remove();
    };
  }, [router]);

  useEffect(() => {
    if (!accessToken) return;

    let tokenSubscription: { remove: () => void } | undefined;
    let cancelled = false;

    void registerForPushNotifications(accessToken);

    // Fires only on the rare occasion the underlying device push token
    // itself changes (e.g. after a fresh install) — not on every app start.
    void getNotificationsModule().then((Notifications) => {
      if (!Notifications || cancelled) return;
      tokenSubscription = Notifications.addPushTokenListener(() => {
        void registerForPushNotifications(accessToken);
      });
    });

    return () => {
      cancelled = true;
      tokenSubscription?.remove();
    };
  }, [accessToken]);

  return <>{children}</>;
}
