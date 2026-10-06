import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Button, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/SkeletonBlock";
import { getNotificationsModule } from "@/features/notifications/push-notifications";
import { useThemeColors } from "@/hooks/use-theme-colors";
import {
  getRiderNotifications,
  markAllRiderNotificationsRead,
  markRiderNotificationRead,
  type RiderNotification,
} from "@/services/api/notificationsApi";
import { useAuthStore } from "@/store/authStore";

const TYPE_ICON: Record<string, string> = {
  new_delivery: "🛵",
  delivery_cancelled: "✗",
  delivery_updated: "ℹ️",
  payment_update: "💳",
  earning_update: "💰",
  account_approved: "✓",
  account_suspended: "⛔",
  document_approved: "✓",
  document_rejected: "⚠️",
  cod_settlement_due: "💵",
  cod_pending: "💵",
  system: "🔔",
};

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Deep-link destination for tapping a notification while already inside the
// app — mirrors what a tapped push notification does in
// features/notifications/notification-provider.tsx, so behavior is
// consistent whichever way the user gets there.
function destinationFor(notification: RiderNotification): { pathname: string; params?: { id: string } } | null {
  if (notification.type === "new_delivery") return { pathname: "/" };
  if (notification.type === "delivery_cancelled" && notification.order_id) {
    return { pathname: "/delivery/[id]", params: { id: notification.order_id } };
  }
  // A delivery that was updated by being reassigned away is no longer
  // this rider's to view — get_rider_delivery_or_404 scopes strictly to
  // Order.rider_id == this rider, so /delivery/[id] would just 404 for
  // them now. The dashboard (their current, actually-theirs deliveries)
  // is the correct landing spot, same as a fresh new_delivery alert.
  if (notification.type === "delivery_updated") return { pathname: "/" };
  if (notification.type === "account_approved" || notification.type === "account_suspended") {
    return { pathname: "/verification" };
  }
  if (notification.type === "document_approved" || notification.type === "document_rejected") {
    return { pathname: "/verification" };
  }
  if (notification.type === "cod_settlement_due") return { pathname: "/wallet" };
  // "Collect cash for this order" needs the order itself, not the wallet
  // (that's for settlement — a different concept, see cod_settlement_due
  // above).
  if (notification.type === "cod_pending" && notification.order_id) {
    return { pathname: "/delivery/[id]", params: { id: notification.order_id } };
  }
  return null;
}

export default function RiderNotificationsScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [notifications, setNotifications] = useState<RiderNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    try {
      const data = await getRiderNotifications(accessToken);
      setNotifications(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load notifications.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  async function handleRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  // Expo Push Integration (Phase 16) — "notification receipt": a push
  // that arrives while this screen is already open and focused (so
  // useFocusEffect above won't re-fire) must still show up without the
  // rider having to manually pull-to-refresh.
  useEffect(() => {
    let subscription: { remove: () => void } | undefined;
    let cancelled = false;

    void getNotificationsModule().then((Notifications) => {
      if (!Notifications || cancelled) return;
      subscription = Notifications.addNotificationReceivedListener(() => {
        void load();
      });
    });

    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, [load]);

  async function handlePress(notification: RiderNotification) {
    if (!accessToken) return;
    if (!notification.is_read) {
      try {
        await markRiderNotificationRead(accessToken, notification.id);
        setNotifications((prev) =>
          prev.map((item) => (item.id === notification.id ? { ...item, is_read: true } : item)),
        );
      } catch {
        // Non-fatal — still navigate even if marking read failed.
      }
    }
    const destination = destinationFor(notification);
    if (destination) router.push(destination as never);
  }

  async function handleMarkAllRead() {
    if (!accessToken) return;
    try {
      setMarkingAll(true);
      await markAllRiderNotificationsRead(accessToken);
      setNotifications((prev) => prev.map((item) => ({ ...item, is_read: true })));
    } catch {
      // Leave the list as-is — the user can retry.
    } finally {
      setMarkingAll(false);
    }
  }

  const unreadCount = notifications.filter((item) => !item.is_read).length;

  if (!accessToken) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <Text style={{ color: colors.text }}>Please log in to continue.</Text>
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.headerRow}>
        <Text style={[styles.title, { color: colors.text }]}>Notifications</Text>
        <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back to dashboard" />
      </View>

      {unreadCount > 0 && (
        <Button
          title={markingAll ? "Marking…" : `Mark all read (${unreadCount})`}
          onPress={handleMarkAllRead}
          disabled={markingAll}
          accessibilityLabel={`Mark all ${unreadCount} notifications read`}
        />
      )}

      {loading ? (
        <>
          <SkeletonCard />
          <SkeletonCard />
        </>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : notifications.length === 0 ? (
        <EmptyState icon="🔕" message="No notifications yet." />
      ) : (
        notifications.map((notification) => (
          <TouchableOpacity
            key={notification.id}
            style={[
              styles.card,
              { borderColor: colors.border, backgroundColor: colors.card },
              !notification.is_read && { borderColor: colors.primary, backgroundColor: colors.primary + "14" },
            ]}
            onPress={() => handlePress(notification)}
            accessibilityRole="button"
            accessibilityLabel={`${notification.is_read ? "" : "Unread. "}${notification.title}. ${notification.body}`}
          >
            <View style={styles.cardRow}>
              <Text style={[styles.cardTitle, { color: colors.text }]}>
                {TYPE_ICON[notification.type] ?? "🔔"} {notification.title}
              </Text>
              {!notification.is_read && <View style={[styles.unreadDot, { backgroundColor: colors.primary }]} />}
            </View>
            <Text style={[styles.cardBody, { color: colors.text }]}>{notification.body}</Text>
            <Text style={[styles.muted, { color: colors.muted }]}>{timeAgo(notification.created_at)}</Text>
          </TouchableOpacity>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  container: { padding: 24, gap: 12, flexGrow: 1 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 24, fontWeight: "700" },
  muted: { fontSize: 12 },
  card: {
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    gap: 4,
  },
  cardRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardTitle: { fontWeight: "700", fontSize: 15, flexShrink: 1 },
  cardBody: { fontSize: 14 },
  unreadDot: { width: 8, height: 8, borderRadius: 4 },
});
