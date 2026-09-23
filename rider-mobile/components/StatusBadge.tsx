import { StyleSheet, Text, View } from "react-native";

import { useThemeColors } from "@/hooks/use-theme-colors";

const LABELS: Record<string, string> = {
  placed: "Placed",
  confirmed: "Confirmed",
  preparing: "Preparing",
  ready_for_pickup: "Ready for Pickup",
  rider_assigned: "Assigned to You",
  picked_up: "Picked Up",
  out_for_delivery: "Out for Delivery",
  delivered: "Delivered",
  cancelled: "Cancelled",
  rejected: "Rejected",
  ACCEPTED: "Accepted",
  REJECTED: "Rejected",
  ARRIVED_AT_RESTAURANT: "Arrived at Restaurant",
  PICKED_UP: "Picked Up",
  OUT_FOR_DELIVERY: "Out for Delivery",
  DELIVERED: "Delivered",
  CANCELLED: "Cancelled",
};

// Three-tier palette: a status is either "in progress" (blue), a good
// terminal outcome (green), or a bad/inactive one (red). Anything not
// listed explicitly falls back to muted grey rather than guessing.
const GOOD = new Set(["delivered", "DELIVERED"]);
const BAD = new Set(["cancelled", "rejected", "CANCELLED", "REJECTED"]);
const IN_PROGRESS = new Set([
  "confirmed", "preparing", "ready_for_pickup", "rider_assigned", "picked_up", "out_for_delivery",
  "ACCEPTED", "ARRIVED_AT_RESTAURANT", "PICKED_UP", "OUT_FOR_DELIVERY",
]);

export function StatusBadge({ status }: { status: string }) {
  const colors = useThemeColors();
  const tone = GOOD.has(status) ? "good" : BAD.has(status) ? "bad" : IN_PROGRESS.has(status) ? "progress" : "neutral";

  const toneColors = {
    good: { bg: colors.success + "22", fg: colors.success },
    bad: { bg: colors.danger + "22", fg: colors.danger },
    progress: { bg: colors.primary + "22", fg: colors.primary },
    neutral: { bg: colors.muted + "22", fg: colors.muted },
  }[tone];

  return (
    <View style={[styles.badge, { backgroundColor: toneColors.bg }]}>
      <Text style={[styles.text, { color: toneColors.fg }]}>{LABELS[status] ?? status}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  text: { fontSize: 12, fontWeight: "700" },
});
