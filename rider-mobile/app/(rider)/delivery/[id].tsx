import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Button, Linking, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { ErrorState } from "@/components/ErrorState";
import { SkeletonBlock, SkeletonCard } from "@/components/SkeletonBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { useAuthStore } from "@/store/authStore";
import { useLocationTrackingStore } from "@/store/locationTrackingStore";
import {
  collectCodPayment,
  completeDelivery,
  getDeliveryDetail,
  markArrivedAtRestaurant,
  pickupDelivery,
  startDelivery,
  type DeliveryDetail,
} from "@/services/api/deliveriesApi";
import { ACTIVE_DELIVERY_STATUSES } from "@/services/api/riderApi";
import { navigateTo } from "@/services/navigation";
import { rupees } from "@/utils/currency";

function toCoordinates(latitude: number | string | null, longitude: number | string | null) {
  if (latitude === null || longitude === null) return null;
  const lat = typeof latitude === "string" ? Number(latitude) : latitude;
  const lng = typeof longitude === "string" ? Number(longitude) : longitude;
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
  return { latitude: lat, longitude: lng };
}

export default function RiderDeliveryDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [delivery, setDelivery] = useState<DeliveryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [completing, setCompleting] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken || !id) return;
    try {
      const data = await getDeliveryDetail(accessToken, id);
      setDelivery(data);
      setError(null);
    } catch (err) {
      setDelivery(null);
      setError(err instanceof Error ? err.message : "Unable to load this delivery.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, id]);

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

  const isActivelyDelivering = delivery ? ACTIVE_DELIVERY_STATUSES.includes(delivery.status) : false;
  // The actual reporting interval runs once, higher up, in (rider)/_layout.tsx
  // (driven by ONLINE-or-active-delivery, not just this screen's delivery
  // status) — this just reads its shared status to render the banner below.
  const sharingState = useLocationTrackingStore((state) => state.state);

  async function handleMarkArrived() {
    if (!accessToken || !id) return;
    try {
      await markArrivedAtRestaurant(accessToken, id);
      await load();
    } catch (err) {
      Alert.alert("Unable to update", err instanceof Error ? err.message : "Please try again.");
    }
  }

  async function handlePickUpOrder() {
    if (!accessToken || !id) return;
    try {
      await pickupDelivery(accessToken, id);
      await load();
    } catch (err) {
      Alert.alert("Unable to update", err instanceof Error ? err.message : "Please try again.");
    }
  }

  async function handleStartDelivery() {
    if (!accessToken || !id) return;
    try {
      await startDelivery(accessToken, id);
      await load();
    } catch (err) {
      Alert.alert("Unable to update", err instanceof Error ? err.message : "Please try again.");
    }
  }

  function confirmCollectCod() {
    if (!delivery?.cod_amount) return;
    // Financial and irreversible — worth a clear confirmation showing the
    // exact figure, unlike the low-stakes workflow steps above.
    Alert.alert(
      "Confirm cash collected",
      `Confirm you collected ${rupees(delivery.cod_amount)} in cash from the customer?`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Confirm", onPress: () => void handleCollectCod() },
      ],
    );
  }

  async function handleCollectCod() {
    if (!accessToken || !id) return;
    try {
      setCollecting(true);
      await collectCodPayment(accessToken, id);
      await load();
    } catch (err) {
      Alert.alert("Unable to collect cash", err instanceof Error ? err.message : "Please try again.");
    } finally {
      setCollecting(false);
    }
  }

  function confirmCompleteDelivery() {
    // Final and irreversible — this is the one action on this screen most
    // worth a deliberate confirmation tap.
    Alert.alert("Mark this delivery complete?", "This confirms the order has been handed to the customer.", [
      { text: "Cancel", style: "cancel" },
      { text: "Mark Delivered", onPress: () => void handleCompleteDelivery() },
    ]);
  }

  async function handleCompleteDelivery() {
    if (!accessToken || !id) return;
    try {
      setCompleting(true);
      await completeDelivery(accessToken, id);
      await load();
    } catch (err) {
      Alert.alert("Unable to mark delivered", err instanceof Error ? err.message : "Please try again.");
    } finally {
      setCompleting(false);
    }
  }

  async function handleNavigateToRestaurant() {
    if (!delivery) return;
    try {
      await navigateTo({
        label: delivery.restaurant_name,
        coordinates: toCoordinates(delivery.restaurant_latitude, delivery.restaurant_longitude),
        address: delivery.restaurant_address,
      });
    } catch (err) {
      Alert.alert("Unable to open navigation", err instanceof Error ? err.message : "Please try again.");
    }
  }

  async function handleNavigateToCustomer() {
    if (!delivery) return;
    try {
      await navigateTo({
        label: delivery.customer_name,
        coordinates: toCoordinates(delivery.delivery_latitude, delivery.delivery_longitude),
        address: `${delivery.delivery_address_line}, ${delivery.delivery_city}`,
      });
    } catch (err) {
      Alert.alert("Unable to open navigation", err instanceof Error ? err.message : "Please try again.");
    }
  }

  if (!accessToken) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <Text style={{ color: colors.text }}>Please log in to continue.</Text>
      </View>
    );
  }

  if (loading) {
    return (
      <ScrollView contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}>
        <SkeletonBlock width="50%" height={24} />
        <SkeletonCard />
        <SkeletonCard />
      </ScrollView>
    );
  }

  if (!delivery) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <ErrorState message={error ?? "Delivery not found."} onRetry={load} />
        <Button title="Back to dashboard" onPress={() => router.replace("/")} accessibilityLabel="Back to dashboard" />
      </View>
    );
  }

  return (
    <ScrollView
      contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <Text style={[styles.title, { color: colors.text }]}>Current Delivery</Text>
      <Text style={[styles.orderNumber, { color: colors.text }]}>{delivery.order_number}</Text>
      <StatusBadge status={delivery.status} />
      {isActivelyDelivering && (
        <Text style={[styles.muted, { color: colors.muted }]}>
          {sharingState === "sharing" && "📍 Sharing your location with the customer"}
          {sharingState === "requesting-permission" && "Requesting location permission…"}
          {sharingState === "denied" && "⚠️ Location permission denied — customer won't see your position"}
          {sharingState === "error" && "⚠️ Couldn't get your location right now"}
        </Text>
      )}

      <Text style={[styles.label, { color: colors.text }]}>Pickup restaurant</Text>
      <Text style={{ color: colors.text }}>{delivery.restaurant_name}</Text>
      <Text style={[styles.muted, { color: colors.muted }]}>{delivery.restaurant_address}</Text>

      <Text style={[styles.label, { color: colors.text }]}>Deliver to</Text>
      <Text style={{ color: colors.text }}>{delivery.customer_name}</Text>
      <Text style={{ color: colors.text }}>{delivery.delivery_address_line}</Text>
      <Text style={{ color: colors.text }}>
        {delivery.delivery_city}, {delivery.delivery_postal_code}
      </Text>
      {delivery.delivery_landmark && (
        <Text style={[styles.muted, { color: colors.muted }]}>Landmark: {delivery.delivery_landmark}</Text>
      )}
      <Text style={[styles.muted, { color: colors.muted }]}>{delivery.delivery_instructions || "No delivery notes"}</Text>

      <Text style={[styles.label, { color: colors.text }]}>Items</Text>
      {delivery.items.map((item) => (
        <Text key={item.id} style={{ color: colors.text }}>
          {item.quantity} × {item.product_name}
        </Text>
      ))}
      <Text style={[styles.muted, { color: colors.muted }]}>Order total: {rupees(delivery.total)}</Text>
      {delivery.cod_amount !== null && (
        <View style={styles.codBox} accessibilityRole="text" accessibilityLabel={`Cash to collect: ${rupees(delivery.cod_amount)}`}>
          <Text style={styles.codLabel}>Cash to Collect</Text>
          <Text style={styles.codAmount}>{rupees(delivery.cod_amount)}</Text>
        </View>
      )}
      {delivery.payment_method === "cod" && delivery.cod_amount === null && delivery.is_paid && (
        <Text style={[styles.collectedBadge, { color: colors.success }]}>✓ Cash Collected</Text>
      )}

      <View style={styles.buttonGroup}>
        <Button
          title="Call Customer"
          onPress={() => {
            if (delivery.customer_phone) void Linking.openURL(`tel:${delivery.customer_phone}`);
            else Alert.alert("No number available");
          }}
          accessibilityLabel="Call customer"
        />
        <Button title="NAVIGATE TO CUSTOMER" onPress={handleNavigateToCustomer} accessibilityLabel="Navigate to customer" />
      </View>

      {/* Go to Restaurant -> [ ARRIVED ] -> [ PICK UP ORDER ] ->
          Order Picked Up -> [ START DELIVERY ] -> OUT FOR DELIVERY */}
      <Text style={[styles.label, { color: colors.text }]}>Delivery workflow</Text>
      <View style={styles.buttonGroup}>
        {delivery.status === "rider_assigned" ? (
          <>
            <Button title="NAVIGATE TO RESTAURANT" onPress={handleNavigateToRestaurant} accessibilityLabel="Navigate to restaurant" />
            {delivery.assignment_status === "ARRIVED_AT_RESTAURANT" ? (
              <Button title="PICK UP ORDER" onPress={handlePickUpOrder} accessibilityLabel="Confirm order picked up" />
            ) : (
              <Button title="ARRIVED" onPress={handleMarkArrived} accessibilityLabel="Mark arrived at restaurant" />
            )}
          </>
        ) : delivery.status === "picked_up" ? (
          <>
            <Text style={[styles.pickedUpBadge, { color: colors.success }]}>✓ Order Picked Up</Text>
            <Button title="START DELIVERY" onPress={handleStartDelivery} accessibilityLabel="Start delivery" />
          </>
        ) : delivery.status === "out_for_delivery" ? (
          <>
            <Text style={[styles.pickedUpBadge, { color: colors.success }]}>OUT FOR DELIVERY</Text>
            {delivery.cod_amount !== null && (
              <Button
                title={collecting ? "Collecting…" : "COLLECT CASH"}
                onPress={confirmCollectCod}
                disabled={collecting}
                accessibilityLabel="Collect cash from customer"
              />
            )}
            <Text style={[styles.label, { color: colors.text }]}>Customer Delivery</Text>
            <Button
              title={completing ? "Marking Delivered…" : "MARK DELIVERED"}
              onPress={confirmCompleteDelivery}
              disabled={completing || delivery.cod_amount !== null}
              accessibilityLabel="Mark delivery complete"
            />
            {delivery.cod_amount !== null && (
              <Text style={[styles.muted, { color: colors.muted }]}>Collect the cash above before marking this delivered.</Text>
            )}
          </>
        ) : delivery.status === "delivered" ? (
          <Text style={[styles.deliveredBadge, { color: colors.success }]}>✓ Delivered Successfully.</Text>
        ) : (
          <Text style={[styles.muted, { color: colors.muted }]}>Status: {delivery.status}</Text>
        )}
      </View>

      <View style={styles.buttonGroup}>
        <Button title="Back to Dashboard" onPress={() => router.back()} accessibilityLabel="Back to dashboard" />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
    gap: 12,
  },
  container: { padding: 24, gap: 6, flexGrow: 1 },
  title: { fontSize: 28, fontWeight: "700" },
  orderNumber: { fontSize: 18, fontWeight: "700" },
  label: { fontSize: 16, fontWeight: "700", marginTop: 12 },
  muted: {},
  codBox: {
    marginTop: 8,
    padding: 12,
    borderRadius: 8,
    backgroundColor: "#fffbeb",
    borderWidth: 1,
    borderColor: "#fde68a",
  },
  codLabel: { fontSize: 13, fontWeight: "600", color: "#92400e" },
  codAmount: { fontWeight: "800", fontSize: 22, color: "#b45309", marginTop: 2 },
  collectedBadge: { fontWeight: "700", marginTop: 8 },
  buttonGroup: { gap: 10, marginTop: 16 },
  pickedUpBadge: { fontSize: 18, fontWeight: "800" },
  deliveredBadge: { fontSize: 20, fontWeight: "800" },
});
