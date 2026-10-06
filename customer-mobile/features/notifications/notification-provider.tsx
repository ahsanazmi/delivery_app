import { useRouter } from "expo-router";
import { PropsWithChildren, useEffect } from "react";

import { useSession } from "@/features/auth/session-context";
import { getNotificationsModule, registerForPushNotifications } from "./push-notifications";

type AppRouter = ReturnType<typeof useRouter>;

// Deep Linking (Phase 27) — one route per notification category, not
// per NotificationType: several distinct types already share a category
// (see NotificationDeepLinkCategory's own docstring) precisely because
// they land on the same screen. The screen itself is always what
// actually authorizes the view (e.g. /track/[id] and /orders/[id] both
// fetch through an endpoint scoped to the signed-in customer's own
// orders) — order_id here is only ever a navigation hint, never trusted
// as proof of access on its own.
export function handleDeepLink(
  router: AppRouter,
  data: Record<string, unknown> | undefined,
  // Background/Terminated App Behavior (Phase 29) — a cold start (app
  // launched by tapping a notification from killed) lands here via the
  // *same* handler as a tap while already running, but needs the
  // opposite navigation method: "replace", not "push". A running app has
  // a real screen stack to push onto; a cold start has none yet, and
  // app/splash.tsx's own auth-based redirect (its own setTimeout, up to
  // 1200ms for an anonymous session) is independently about to call its
  // own router.replace("/home") — replace() here is what guarantees the
  // deep link is the navigation state's last word instead of being
  // silently overwritten the moment splash's redirect finishes after it.
  method: "push" | "replace" = "push",
) {
  if (!data) return;
  const orderId = typeof data.order_id === "string" ? data.order_id : null;
  const navigate = router[method];

  switch (data.type) {
    case "order_status":
      if (orderId) navigate({ pathname: "/track/[id]", params: { id: orderId } });
      break;
    // Payment/refund events land on the order detail screen — the
    // payment status card (and retry action, for a failure) lives
    // there, not on a separate standalone payment route.
    case "payment_failed":
    case "payment_success":
    case "refund":
      if (orderId) navigate({ pathname: "/orders/[id]", params: { id: orderId } });
      break;
    case "promotion":
      navigate("/home");
      break;
    default:
      // An unrecognized/future category is a safe no-op — never crash
      // on a tap just because this client doesn't know this type yet.
      break;
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
    let coldStartTimeout: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    void getNotificationsModule().then((Notifications) => {
      if (!Notifications || cancelled) return;

      responseSubscription = Notifications.addNotificationResponseReceivedListener((response) => {
        handleDeepLink(router, response.notification.request.content.data as Record<string, unknown>);
      });

      void Notifications.getLastNotificationResponseAsync().then((response) => {
        if (!response) return;
        const data = response.notification.request.content.data as Record<string, unknown>;
        // Deferred past splash.tsx's own worst-case redirect delay
        // (1200ms, anonymous session) — see handleDeepLink's own "replace"
        // param note above for why this ordering matters.
        const timeout = setTimeout(() => {
          if (!cancelled) handleDeepLink(router, data, "replace");
        }, 1300);
        coldStartTimeout = timeout;
      });
    });

    return () => {
      cancelled = true;
      responseSubscription?.remove();
      if (coldStartTimeout) clearTimeout(coldStartTimeout);
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
