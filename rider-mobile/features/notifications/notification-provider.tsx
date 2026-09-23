import { useRouter } from "expo-router";
import { PropsWithChildren, useEffect } from "react";

import { useAuthStore } from "@/store/authStore";
import { getNotificationsModule, registerForPushNotifications } from "./push-notifications";

type AppRouter = ReturnType<typeof useRouter>;

function handleDeepLink(router: AppRouter, data: Record<string, unknown> | undefined) {
  if (!data) return;
  const orderId = typeof data.order_id === "string" ? data.order_id : null;

  switch (data.type) {
    case "new_delivery":
      // The dashboard's own Available Deliveries list is the actual accept
      // surface — a rider must still choose to accept, so this lands them
      // there rather than deep-linking straight into a delivery they don't
      // have yet.
      router.push("/");
      break;
    case "delivery_cancelled":
      if (orderId) router.push({ pathname: "/delivery/[id]", params: { id: orderId } });
      else router.push("/");
      break;
    case "account_approved":
    case "account_suspended":
      router.push("/verification");
      break;
    default:
      router.push("/");
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
  const accessToken = useAuthStore((state) => state.accessToken);
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
