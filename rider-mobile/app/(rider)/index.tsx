import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Linking, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/SkeletonBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { acceptDelivery, rejectDelivery } from "@/services/api/deliveriesApi";
import { getRiderNotifications } from "@/services/api/notificationsApi";
import { listRiderOrders, type RiderApprovalStatus, type RiderOrder } from "@/services/api/riderApi";
import { rupees } from "@/utils/currency";
import { useAuthStore } from "@/store/authStore";
import { useRiderStore } from "@/store/riderStore";

const SESSION_REFRESH_INTERVAL_MS = 10 * 60 * 1000;
const UNREAD_POLL_INTERVAL_MS = 60 * 1000;

const STATUS_DISPLAY: Record<RiderApprovalStatus, { icon: string; label: string }> = {
  APPROVED: { icon: "✓", label: "Approved" },
  PENDING: { icon: "⏳", label: "Under Review" },
  REJECTED: { icon: "✗", label: "Rejected" },
  SUSPENDED: { icon: "⛔", label: "Suspended" },
};

export default function RiderDashboardScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const refreshSession = useAuthStore((state) => state.refreshSession);
  const riderStatus = useRiderStore((state) => state.status);
  const statusError = useRiderStore((state) => state.statusError);
  const fetchStatus = useRiderStore((state) => state.fetchStatus);
  const setOnline = useRiderStore((state) => state.setOnline);
  const dashboard = useRiderStore((state) => state.dashboard);
  const dashboardError = useRiderStore((state) => state.dashboardError);
  const fetchDashboard = useRiderStore((state) => state.fetchDashboard);
  const availableDeliveries = useRiderStore((state) => state.availableDeliveries);
  const availableDeliveriesError = useRiderStore((state) => state.availableDeliveriesError);
  const fetchAvailableDeliveries = useRiderStore((state) => state.fetchAvailableDeliveries);

  const [orders, setOrders] = useState<RiderOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [togglingOnline, setTogglingOnline] = useState(false);
  const [respondingTo, setRespondingTo] = useState<string | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);

  const load = useCallback(async () => {
    if (!accessToken) return;
    try {
      const [data] = await Promise.all([
        listRiderOrders(accessToken),
        fetchStatus(accessToken),
        fetchDashboard(accessToken),
        fetchAvailableDeliveries(accessToken),
      ]);
      setOrders(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load rider orders");
    } finally {
      setLoading(false);
    }
  }, [accessToken, fetchStatus, fetchDashboard, fetchAvailableDeliveries]);

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

  // Keeps a long-open session's access token from silently expiring —
  // without this, a rider who leaves the app open past the token's TTL
  // would start seeing every request fail until they manually re-login.
  useEffect(() => {
    const interval = setInterval(() => void refreshSession(), SESSION_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshSession]);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    function poll() {
      void getRiderNotifications(accessToken!).then((items) => {
        if (!cancelled) setUnreadCount(items.filter((item) => !item.is_read).length);
      }).catch(() => {
        // Non-critical — the badge just stays at its last known count.
      });
    }
    poll();
    const interval = setInterval(poll, UNREAD_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [accessToken]);

  async function handleToggleOnline() {
    if (!accessToken || !riderStatus) return;
    setTogglingOnline(true);
    await setOnline(accessToken, !riderStatus.is_online);
    await Promise.all([fetchDashboard(accessToken), fetchAvailableDeliveries(accessToken)]);
    setTogglingOnline(false);
  }

  async function handleAcceptDelivery(orderId: string) {
    if (!accessToken) return;
    setRespondingTo(orderId);
    try {
      await acceptDelivery(accessToken, orderId);
      // Someone else could have won it a moment ago even if we didn't hit an
      // error — refresh everything so the lists and current assignment
      // reflect exactly what actually happened, not what we hoped happened.
      await Promise.all([
        listRiderOrders(accessToken).then(setOrders),
        fetchDashboard(accessToken),
        fetchAvailableDeliveries(accessToken),
      ]);
    } catch (err) {
      Alert.alert(
        "Unable to accept",
        err instanceof Error ? err.message : "This delivery may have already been taken by another rider.",
      );
      await fetchAvailableDeliveries(accessToken);
    } finally {
      setRespondingTo(null);
    }
  }

  function confirmRejectDelivery(orderId: string, restaurantName: string) {
    // Rejecting is a one-way door for this rider (it won't be offered to
    // them again for this order) — worth one confirmation tap, unlike the
    // lower-stakes in-flight actions on the delivery screen itself.
    Alert.alert("Reject this delivery?", `You won't be offered "${restaurantName}" again.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Reject", style: "destructive", onPress: () => void handleRejectDelivery(orderId) },
    ]);
  }

  async function handleRejectDelivery(orderId: string) {
    if (!accessToken) return;
    setRespondingTo(orderId);
    try {
      await rejectDelivery(accessToken, orderId);
      await fetchAvailableDeliveries(accessToken);
    } catch (err) {
      Alert.alert("Unable to reject", err instanceof Error ? err.message : "Please try again.");
    } finally {
      setRespondingTo(null);
    }
  }

  if (loading) {
    return (
      <ScrollView contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}>
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </ScrollView>
    );
  }

  const approvalStatus = riderStatus?.approval_status ?? "PENDING";
  const display = STATUS_DISPLAY[approvalStatus];
  const assignment = dashboard?.current_assignment ?? null;

  return (
    <ScrollView
      contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.headerRow}>
        <Text style={[styles.title, { color: colors.text }]}>Dashboard</Text>
        <View style={styles.headerActions}>
          <TouchableOpacity
            style={styles.iconButton}
            onPress={() => router.push("/notifications")}
            accessibilityRole="button"
            accessibilityLabel={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
          >
            <Text style={styles.iconButtonText}>🔔</Text>
            {unreadCount > 0 && (
              <View style={[styles.badge, { backgroundColor: colors.danger }]}>
                <Text style={styles.badgeText}>{unreadCount > 9 ? "9+" : unreadCount}</Text>
              </View>
            )}
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.iconButton}
            onPress={() => router.push("/profile")}
            accessibilityRole="button"
            accessibilityLabel="Profile and settings"
          >
            <Text style={styles.iconButtonText}>👤</Text>
          </TouchableOpacity>
        </View>
      </View>

      <View style={[styles.statusCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
        <Text style={[styles.statusCardLabel, { color: colors.muted }]}>Account Status:</Text>
        <Text style={[styles.statusCardValue, { color: colors.text }]}>
          {display.icon} {display.label}
        </Text>
        {approvalStatus !== "APPROVED" && (
          <Text
            style={[styles.statusLink, { color: colors.primary }]}
            onPress={() => router.push("/verification")}
            accessibilityRole="link"
          >
            View details
          </Text>
        )}
      </View>

      {/* ┌ Rider Status   🟢 ONLINE ┐ */}
      <View style={[styles.onlineCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
        <View style={styles.onlineHeaderRow}>
          <Text style={[styles.sectionTitle, { color: colors.text }]}>Rider Status</Text>
          <Text style={[styles.onlineStateLabel, { color: riderStatus?.is_online ? colors.success : colors.muted }]}>
            {riderStatus?.is_online ? "🟢 ONLINE" : "OFFLINE"}
          </Text>
        </View>
        <Button
          title={togglingOnline ? "Please wait..." : riderStatus?.is_online ? "GO OFFLINE" : "GO ONLINE"}
          onPress={handleToggleOnline}
          disabled={togglingOnline || (!riderStatus?.is_online && !riderStatus?.can_go_online)}
          accessibilityLabel={riderStatus?.is_online ? "Go offline" : "Go online"}
        />
        {!riderStatus?.is_online && riderStatus?.online_blocked_reason && (
          <Text style={[styles.hint, { color: colors.muted }]}>{riderStatus.online_blocked_reason}</Text>
        )}
      </View>
      {statusError ? <ErrorState message={statusError} onRetry={() => accessToken && fetchStatus(accessToken)} /> : null}

      {/* ├ Deliveries │ Earnings ┤ */}
      <View style={styles.statsRow}>
        <View style={[styles.statBox, { borderColor: colors.border, backgroundColor: colors.card }]}>
          <Text style={[styles.statLabel, { color: colors.muted }]}>Deliveries</Text>
          <Text style={[styles.statValue, { color: colors.text }]}>{dashboard?.pending_deliveries_count ?? 0} active</Text>
          <Text style={[styles.statSub, { color: colors.muted }]}>{dashboard?.completed_deliveries_count ?? 0} completed all-time</Text>
        </View>
        <View style={[styles.statBox, { borderColor: colors.border, backgroundColor: colors.card }]}>
          <Text style={[styles.statLabel, { color: colors.muted }]}>Earnings</Text>
          <Text style={[styles.statValue, { color: colors.text }]}>{rupees(dashboard?.today_earnings ?? 0)}</Text>
          <Text style={[styles.statSub, { color: colors.muted }]}>today</Text>
        </View>
      </View>

      {/* ├ Current Delivery ┤ */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Current Delivery</Text>
        {assignment ? (
          <TouchableOpacity
            style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}
            onPress={() => router.push({ pathname: "/delivery/[id]", params: { id: assignment.id } })}
            accessibilityRole="button"
            accessibilityLabel={`Open current delivery, order ${assignment.order_number}`}
          >
            <Text style={[styles.orderNumber, { color: colors.text }]}>{assignment.order_number}</Text>
            <Text style={[styles.muted, { color: colors.muted }]}>{assignment.restaurant_name ?? "Restaurant"}</Text>
            <StatusBadge status={assignment.status} />
          </TouchableOpacity>
        ) : (
          <EmptyState icon="🛵" message="No active delivery. Go online to start receiving requests." />
        )}
      </View>
      {dashboardError ? (
        <ErrorState message={dashboardError} onRetry={() => accessToken && fetchDashboard(accessToken)} />
      ) : null}

      {/* ├ Today's Summary ┤ */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Today&apos;s Summary</Text>
        <View style={[styles.summaryCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
          <View style={styles.summaryRow}>
            <Text style={[styles.muted, { color: colors.muted }]}>Deliveries today</Text>
            <Text style={[styles.summaryValue, { color: colors.text }]}>{dashboard?.today_deliveries_count ?? 0}</Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={[styles.muted, { color: colors.muted }]}>Earnings today</Text>
            <Text style={[styles.summaryValue, { color: colors.text }]}>{rupees(dashboard?.today_earnings ?? 0)}</Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={[styles.muted, { color: colors.muted }]}>Pending deliveries</Text>
            <Text style={[styles.summaryValue, { color: colors.text }]}>{dashboard?.pending_deliveries_count ?? 0}</Text>
          </View>
        </View>
      </View>

      {/* New delivery requests a rider can see once online — separate from
          "My Deliveries" below, which are already assigned to this rider. */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Available Deliveries</Text>
        {!riderStatus?.is_online ? (
          <EmptyState icon="💤" message="Go online to see available deliveries." />
        ) : availableDeliveriesError ? (
          <ErrorState message={availableDeliveriesError} onRetry={() => accessToken && fetchAvailableDeliveries(accessToken)} />
        ) : availableDeliveries.length === 0 ? (
          <EmptyState icon="🔍" message="No available deliveries right now." />
        ) : (
          availableDeliveries.map((delivery) => {
            const busy = respondingTo === delivery.order_id;
            return (
              <View key={delivery.assignment_id} style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
                <Text style={[styles.newDeliveryLabel, { color: colors.primary }]}>New Delivery</Text>
                <Text style={[styles.orderNumber, { color: colors.text }]}>{delivery.restaurant_name}</Text>
                <Text style={[styles.muted, { color: colors.muted }]}>{delivery.restaurant_address}</Text>
                <Text style={[styles.muted, { color: colors.muted }]}>
                  Distance: {delivery.estimated_distance_km !== null ? `${delivery.estimated_distance_km} km` : "Unknown"}
                </Text>
                <Text style={[styles.muted, { color: colors.muted }]}>Estimated earning: {rupees(delivery.estimated_earning)}</Text>
                <View style={styles.buttonRow}>
                  <Button
                    title={busy ? "Please wait..." : "ACCEPT"}
                    onPress={() => handleAcceptDelivery(delivery.order_id)}
                    disabled={busy}
                    accessibilityLabel={`Accept delivery from ${delivery.restaurant_name}`}
                  />
                  <Button
                    title="REJECT"
                    color={colors.danger}
                    onPress={() => confirmRejectDelivery(delivery.order_id, delivery.restaurant_name)}
                    disabled={busy}
                    accessibilityLabel={`Reject delivery from ${delivery.restaurant_name}`}
                  />
                </View>
              </View>
            );
          })
        )}
      </View>

      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>My Deliveries</Text>
        {error ? <ErrorState message={error} onRetry={load} /> : null}
        {orders.length === 0 ? (
          <EmptyState icon="📦" message="No delivery assignments yet." />
        ) : (
          orders.map((order) => (
            <View key={order.id} style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
              <Text style={[styles.orderNumber, { color: colors.text }]}>{order.order_number}</Text>
              <Text style={[styles.muted, { color: colors.muted }]}>{order.restaurant_name ?? "Restaurant"}</Text>
              <Text style={[styles.muted, { color: colors.muted }]}>Customer: {order.address_line}</Text>
              <StatusBadge status={order.status} />
              <View style={styles.buttonRow}>
                <Button
                  title="Open delivery"
                  onPress={() => router.push({ pathname: "/delivery/[id]", params: { id: order.id } })}
                  accessibilityLabel={`Open delivery, order ${order.order_number}`}
                />
                <Button
                  title="Open Google Maps"
                  onPress={() => {
                    const query = encodeURIComponent(`${order.address_line}, ${order.city}`);
                    void Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${query}`);
                  }}
                  accessibilityLabel="Open delivery address in Google Maps"
                />
              </View>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20, gap: 16, flexGrow: 1 },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  headerActions: { flexDirection: "row", gap: 8 },
  iconButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
  },
  iconButtonText: { fontSize: 22 },
  badge: {
    position: "absolute",
    top: 2,
    right: 2,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 3,
  },
  badgeText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  title: { fontSize: 26, fontWeight: "700" },
  statusCard: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
  },
  statusCardLabel: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  statusCardValue: { fontSize: 20, fontWeight: "700", marginTop: 2 },
  statusLink: { fontSize: 13, marginTop: 6 },
  onlineCard: {
    gap: 8,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
  },
  onlineHeaderRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  onlineStateLabel: { fontSize: 16, fontWeight: "800" },
  hint: { fontSize: 13 },
  statsRow: { flexDirection: "row", gap: 12 },
  statBox: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 2,
  },
  statLabel: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  statValue: { fontSize: 20, fontWeight: "800" },
  statSub: { fontSize: 12 },
  section: { gap: 8 },
  sectionTitle: { fontSize: 16, fontWeight: "700" },
  summaryCard: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  summaryRow: { flexDirection: "row", justifyContent: "space-between" },
  summaryValue: { fontWeight: "700" },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  orderNumber: { fontSize: 18, fontWeight: "700" },
  newDeliveryLabel: { fontSize: 11, fontWeight: "800", textTransform: "uppercase" },
  buttonRow: { flexDirection: "row", gap: 8, marginTop: 4 },
  muted: {},
});
