import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Button, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/SkeletonBlock";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { getRiderEarningsSummary, type RiderEarningsSummary } from "@/services/api/earningsApi";
import { useAuthStore } from "@/store/authStore";
import { rupees } from "@/utils/currency";

export default function RiderEarningsScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [summary, setSummary] = useState<RiderEarningsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    try {
      const data = await getRiderEarningsSummary(accessToken);
      setSummary(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load earnings.");
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
        <Text style={[styles.title, { color: colors.text }]}>Earnings</Text>
        <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back to dashboard" />
      </View>

      {loading ? (
        <>
          <SkeletonCard />
          <SkeletonCard />
        </>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : summary ? (
        <>
          <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <Text style={[styles.cardLabel, { color: colors.muted }]}>Today&apos;s Earnings</Text>
            <Text style={[styles.cardAmount, { color: colors.success }]}>{rupees(summary.today.total)}</Text>
          </View>

          <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <Text style={[styles.cardLabel, { color: colors.muted }]}>Weekly Earnings</Text>
            <Text style={[styles.cardAmount, { color: colors.success }]}>{rupees(summary.week.total)}</Text>
          </View>

          <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <Text style={[styles.cardLabel, { color: colors.muted }]}>Monthly Earnings</Text>
            <Text style={[styles.cardAmount, { color: colors.success }]}>{rupees(summary.month.total)}</Text>
          </View>

          <View style={styles.statsRow}>
            <View style={[styles.card, styles.statCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
              <Text style={[styles.cardLabel, { color: colors.muted }]}>Total Deliveries</Text>
              <Text style={[styles.cardAmount, { color: colors.text }]}>{summary.total_deliveries}</Text>
            </View>
            <View style={[styles.card, styles.statCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
              <Text style={[styles.cardLabel, { color: colors.muted }]}>Average Earning</Text>
              <Text style={[styles.cardAmount, { color: colors.text }]}>{rupees(summary.average_earning)}</Text>
            </View>
          </View>

          <Text style={[styles.sectionTitle, { color: colors.text }]}>Today&apos;s Breakdown</Text>
          <View style={[styles.breakdownCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <View style={styles.breakdownRow}>
              <Text style={{ color: colors.muted }}>Delivery Fee</Text>
              <Text style={{ color: colors.text }}>{rupees(summary.today.delivery_fee)}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={{ color: colors.muted }}>Incentive</Text>
              <Text style={{ color: colors.text }}>{rupees(summary.today.incentive)}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={{ color: colors.muted }}>Bonus</Text>
              <Text style={{ color: colors.text }}>{rupees(summary.today.bonus)}</Text>
            </View>
            <View style={styles.breakdownRow}>
              <Text style={{ color: colors.muted }}>Adjustment</Text>
              <Text style={{ color: colors.text }}>{rupees(summary.today.adjustment)}</Text>
            </View>
          </View>
        </>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  container: { padding: 24, gap: 12, flexGrow: 1 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 24, fontWeight: "700" },
  card: {
    padding: 16,
    borderRadius: 10,
    borderWidth: 1,
    gap: 4,
  },
  cardLabel: { fontSize: 14, fontWeight: "600" },
  cardAmount: { fontSize: 24, fontWeight: "800" },
  statsRow: { flexDirection: "row", gap: 12 },
  statCard: { flex: 1 },
  sectionTitle: { fontSize: 16, fontWeight: "700", marginTop: 12 },
  breakdownCard: {
    padding: 16,
    borderRadius: 10,
    borderWidth: 1,
    gap: 8,
  },
  breakdownRow: { flexDirection: "row", justifyContent: "space-between" },
});
