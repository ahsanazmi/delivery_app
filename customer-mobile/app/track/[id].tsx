import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { RiderMap } from "@/features/tracking/RiderMap";
import { useOrderTracking } from "@/features/tracking/use-order-tracking";
import type { OrderStatus } from "@/services/api/ordersApi";

const TIMELINE_STEPS: { status: OrderStatus; label: string }[] = [
  { status: "placed", label: "Order Placed" },
  { status: "confirmed", label: "Confirmed" },
  { status: "preparing", label: "Preparing" },
  { status: "ready_for_pickup", label: "Ready for Pickup" },
  { status: "rider_assigned", label: "Rider Assigned" },
  { status: "picked_up", label: "Picked Up" },
  { status: "out_for_delivery", label: "Out for Delivery" },
  { status: "delivered", label: "Delivered" },
];

const EARTH_RADIUS_KM = 6371;

function distanceKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function secondsAgo(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
}

function relativeTimeLabel(iso: string): string {
  const seconds = secondsAgo(iso);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  return `${minutes}m ago`;
}

export default function TrackOrderScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user, accessToken } = useSession();
  const { tracking, error, connectionState, refresh } = useOrderTracking(accessToken, id);

  // Re-render every few seconds so "Xs ago" stays fresh without needing a
  // fresh network message.
  const [, forceTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => forceTick((tick) => tick + 1), 5000);
    return () => clearInterval(interval);
  }, []);

  if (!user || !accessToken) return <Redirect href="/login" />;
  if (!id) return <Redirect href="/orders" />;

  const isCancelledOrRejected = tracking?.order_status === "cancelled" || tracking?.order_status === "rejected";
  const reachedStatuses = new Set(tracking?.status_history.map((entry) => entry.status) ?? []);
  const riderLocation = tracking?.rider_location ?? null;
  const distance =
    riderLocation && tracking?.delivery_latitude != null && tracking?.delivery_longitude != null
      ? distanceKm(riderLocation.latitude, riderLocation.longitude, tracking.delivery_latitude, tracking.delivery_longitude)
      : null;

  const openInMaps = () => {
    if (!riderLocation) return;
    const url = `https://www.google.com/maps/search/?api=1&query=${riderLocation.latitude},${riderLocation.longitude}`;
    void Linking.openURL(url);
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Track order</Text>
        <View style={styles.headerSpacer} />
      </View>

      {connectionState !== "connected" && !isCancelledOrRejected && tracking && (
        <View style={styles.connectionBanner}>
          <Text style={styles.connectionText}>
            {connectionState === "connecting" ? "Connecting for live updates…" : "Reconnecting… showing the latest we have"}
          </Text>
        </View>
      )}

      {!tracking && !error ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error && !tracking ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.retryButton} onPress={refresh}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : tracking ? (
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.orderNumber}>{tracking.order_number}</Text>

          {isCancelledOrRejected ? (
            <View style={styles.cancelledBanner}>
              <Text style={styles.cancelledText}>
                This order was {tracking.order_status === "cancelled" ? "cancelled" : "rejected"}.
              </Text>
            </View>
          ) : (
            <>
              {tracking.estimated_delivery_at && (
                <View style={styles.etaCard}>
                  <Text style={styles.etaLabel}>Estimated delivery</Text>
                  <Text style={styles.etaValue}>
                    {new Date(tracking.estimated_delivery_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </Text>
                </View>
              )}

              <View style={styles.timelineCard}>
                {TIMELINE_STEPS.map((step, index) => {
                  const done = reachedStatuses.has(step.status);
                  const current = tracking.order_status === step.status;
                  const isLast = index === TIMELINE_STEPS.length - 1;
                  return (
                    <View key={step.status} style={styles.timelineRow}>
                      <View style={styles.timelineMarkerColumn}>
                        <View
                          style={[
                            styles.timelineDot,
                            done && styles.timelineDotDone,
                            current && styles.timelineDotCurrent,
                          ]}
                        />
                        {!isLast && (
                          <View style={[styles.timelineLine, done && styles.timelineLineDone]} />
                        )}
                      </View>
                      <Text
                        style={[
                          styles.timelineLabel,
                          done && styles.timelineLabelDone,
                          current && styles.timelineLabelCurrent,
                        ]}
                      >
                        {step.label}
                      </Text>
                    </View>
                  );
                })}
              </View>

              <View style={styles.card}>
                <Text style={styles.sectionTitle}>Delivery partner</Text>
                {tracking.rider ? (
                  <>
                    <Text style={styles.riderName}>{tracking.rider.name}</Text>
                    {tracking.rider.phone && <Text style={styles.meta}>{tracking.rider.phone}</Text>}
                  </>
                ) : (
                  <Text style={styles.meta}>Waiting for a rider to be assigned.</Text>
                )}
              </View>

              {riderLocation ? (
                <View style={styles.mapCard}>
                  <RiderMap
                    riderLocation={riderLocation}
                    deliveryLocation={
                      tracking.delivery_latitude != null && tracking.delivery_longitude != null
                        ? { latitude: tracking.delivery_latitude, longitude: tracking.delivery_longitude }
                        : null
                    }
                  />
                  <View style={styles.mapFooter}>
                    <Text style={styles.mapFooterTitle}>
                      {distance !== null ? `${distance.toFixed(1)} km away` : "Rider location live"}
                    </Text>
                    <Text style={styles.mapFooterMeta}>Updated {relativeTimeLabel(riderLocation.updated_at)}</Text>
                    <Pressable onPress={openInMaps}>
                      <Text style={styles.mapAction}>Open in Google Maps</Text>
                    </Pressable>
                  </View>
                </View>
              ) : (
                <View style={styles.mapPlaceholder}>
                  <Text style={styles.mapEmoji}>🗺️</Text>
                  <Text style={styles.mapText}>
                    {tracking.assignment_status === "assigned"
                      ? "Waiting for the rider's location…"
                      : "Rider location will appear once one is assigned."}
                  </Text>
                </View>
              )}
            </>
          )}
        </ScrollView>
      ) : null}
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
  headerSpacer: { width: 40 },
  connectionBanner: {
    marginHorizontal: 20,
    marginBottom: 4,
    backgroundColor: "#FFF3EE",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  connectionText: { color: "#8A4B12", fontSize: 12, fontWeight: "700" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", marginBottom: 14, lineHeight: 21 },
  retryButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
  content: { padding: 20, paddingBottom: 40, gap: 16 },
  orderNumber: { color: "#241913", fontWeight: "800", fontSize: 16 },
  cancelledBanner: {
    backgroundColor: "#FEE4E2",
    borderRadius: 14,
    padding: 16,
  },
  cancelledText: { color: "#B42318", fontWeight: "800" },
  etaCard: {
    backgroundColor: "#FFF3EE",
    borderRadius: 14,
    padding: 16,
  },
  etaLabel: { color: "#8A4B12", fontSize: 12, fontWeight: "700" },
  etaValue: { color: "#241913", fontSize: 22, fontWeight: "800", marginTop: 4 },
  timelineCard: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 20,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  timelineRow: { flexDirection: "row", alignItems: "flex-start" },
  timelineMarkerColumn: { alignItems: "center", width: 24 },
  timelineDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: "#EADDD6",
  },
  timelineDotDone: { backgroundColor: "#1D8E4E" },
  timelineDotCurrent: { backgroundColor: "#FF5A1F" },
  timelineLine: {
    width: 2,
    flex: 1,
    minHeight: 24,
    backgroundColor: "#EADDD6",
  },
  timelineLineDone: { backgroundColor: "#1D8E4E" },
  timelineLabel: {
    color: "#8A7267",
    fontWeight: "600",
    marginLeft: 12,
    paddingBottom: 24,
  },
  timelineLabelDone: { color: "#241913", fontWeight: "700" },
  timelineLabelCurrent: { color: "#FF5A1F", fontWeight: "800" },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  sectionTitle: { color: "#241913", fontWeight: "800", fontSize: 15, marginBottom: 8 },
  riderName: { color: "#241913", fontWeight: "700" },
  meta: { color: "#6D625D", marginTop: 4 },
  mapPlaceholder: {
    backgroundColor: "#F3ECE6",
    borderRadius: 18,
    paddingVertical: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  mapEmoji: { fontSize: 32, marginBottom: 8 },
  mapText: { color: "#8A7267", fontWeight: "600", textAlign: "center", paddingHorizontal: 20 },
  mapCard: {
    backgroundColor: "#241913",
    borderRadius: 18,
    overflow: "hidden",
  },
  mapFooter: {
    paddingVertical: 16,
    paddingHorizontal: 18,
  },
  mapFooterTitle: { color: "#fff", fontWeight: "800", fontSize: 16 },
  mapFooterMeta: { color: "#C8B8B0", fontSize: 12, marginTop: 4 },
  mapAction: { color: "#FFD9C2", fontWeight: "800", fontSize: 13, marginTop: 10 },
});
