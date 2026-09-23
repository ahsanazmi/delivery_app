import { Redirect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    RefreshControl,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
    getNotifications,
    markAllNotificationsRead,
    markNotificationRead,
    type Notification,
    type NotificationType,
} from "@/services/api/notificationsApi";

const TYPE_ICON: Record<NotificationType, string> = {
  order_placed: "🧾",
  order_confirmed: "✅",
  order_preparing: "👨‍🍳",
  order_ready: "🍽️",
  rider_assigned: "🛵",
  order_picked_up: "🥡",
  order_out_for_delivery: "🚴",
  order_delivered: "📦",
  order_cancelled: "❌",
  order_rejected: "🚫",
  payment_update: "💳",
  promotion: "🎁",
  system: "🔔",
};

export default function NotificationsScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setError(null);
    try {
      const data = await getNotifications(accessToken);
      setNotifications(data);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load notifications.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [accessToken]);

  useEffect(() => {
    load();
  }, [load]);

  function handleRefresh() {
    setRefreshing(true);
    load();
  }

  async function handleOpen(notification: Notification) {
    if (!accessToken) return;
    if (!notification.is_read) {
      setNotifications((current) =>
        current.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n)),
      );
      markNotificationRead(accessToken, notification.id).catch(() => undefined);
    }
    if (notification.order_id) {
      router.push({ pathname: "/orders/[id]", params: { id: notification.order_id } });
    }
  }

  async function handleMarkAllRead() {
    if (!accessToken) return;
    setNotifications((current) => current.map((n) => ({ ...n, is_read: true })));
    try {
      await markAllNotificationsRead(accessToken);
    } catch {
      load();
    }
  }

  if (!user || !accessToken) return <Redirect href="/login" />;

  const hasUnread = notifications.some((n) => !n.is_read);

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Notifications</Text>
        <Pressable
          onPress={handleMarkAllRead}
          style={styles.markAllButton}
          disabled={!hasUnread}
        >
          <Text style={[styles.markAllText, !hasUnread && styles.markAllTextDisabled]}>
            Mark all read
          </Text>
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.retryButton} onPress={load}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : notifications.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyEmoji}>🔔</Text>
          <Text style={styles.emptyTitle}>No notifications yet</Text>
          <Text style={styles.emptyCopy}>
            Updates about your orders and offers will show up here.
          </Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor="#FF5A1F" />}
        >
          {notifications.map((notification) => (
            <Pressable
              key={notification.id}
              style={[styles.card, !notification.is_read && styles.cardUnread]}
              onPress={() => handleOpen(notification)}
            >
              <Text style={styles.icon}>{TYPE_ICON[notification.type] ?? "🔔"}</Text>
              <View style={styles.cardBody}>
                <View style={styles.cardHeadingRow}>
                  <Text style={styles.cardTitle}>{notification.title}</Text>
                  {!notification.is_read && <View style={styles.unreadDot} />}
                </View>
                <Text style={styles.cardBodyText}>{notification.body}</Text>
                <Text style={styles.cardDate}>
                  {new Date(notification.created_at).toLocaleString()}
                </Text>
              </View>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 8,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: "#fff",
    justifyContent: "center",
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  backText: { color: "#241913", fontSize: 24, fontWeight: "700" },
  title: { fontSize: 22, fontWeight: "800", color: "#241913" },
  markAllButton: { paddingHorizontal: 8, paddingVertical: 8 },
  markAllText: { color: "#D83B05", fontWeight: "700", fontSize: 13 },
  markAllTextDisabled: { color: "#C9BEB7" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", marginBottom: 14, lineHeight: 21 },
  retryButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
  content: { padding: 20, paddingBottom: 40, gap: 12 },
  card: {
    flexDirection: "row",
    gap: 12,
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 14,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  cardUnread: { backgroundColor: "#FFF8F5", borderColor: "#FFDCC7" },
  icon: { fontSize: 22 },
  cardBody: { flex: 1 },
  cardHeadingRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardTitle: { color: "#241913", fontWeight: "800", fontSize: 15, flex: 1 },
  unreadDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "#FF5A1F" },
  cardBodyText: { color: "#5F5049", marginTop: 4, lineHeight: 19 },
  cardDate: { color: "#8A7267", fontSize: 12, marginTop: 8 },
  emptyState: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 28,
  },
  emptyEmoji: { fontSize: 54 },
  emptyTitle: {
    marginTop: 18,
    fontSize: 22,
    fontWeight: "800",
    color: "#241913",
  },
  emptyCopy: {
    marginTop: 8,
    color: "#6D625D",
    textAlign: "center",
    lineHeight: 22,
  },
});
