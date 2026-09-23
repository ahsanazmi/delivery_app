import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Button, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/SkeletonBlock";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { getRiderWallet, listRiderSettlements, type RiderSettlement, type RiderWallet } from "@/services/api/walletApi";
import { useAuthStore } from "@/store/authStore";
import { rupees } from "@/utils/currency";

const SETTLEMENTS_PAGE_SIZE = 20;

function isNegative(value: number | string): boolean {
  return Number(value) < 0;
}

function settlementTypeLabel(type: RiderSettlement["settlement_type"]): string {
  return type === "PAYOUT" ? "Paid out to you" : "Remitted to platform";
}

export default function RiderWalletScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [wallet, setWallet] = useState<RiderWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [settlements, setSettlements] = useState<RiderSettlement[]>([]);
  const [settlementsPage, setSettlementsPage] = useState(1);
  const [settlementsHasMore, setSettlementsHasMore] = useState(false);
  const [settlementsLoading, setSettlementsLoading] = useState(true);
  const [settlementsLoadingMore, setSettlementsLoadingMore] = useState(false);
  const [settlementsError, setSettlementsError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    try {
      const data = await getRiderWallet(accessToken);
      setWallet(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load wallet.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  const loadSettlements = useCallback(async () => {
    if (!accessToken) return;
    try {
      const results = await listRiderSettlements(accessToken, { page: 1, limit: SETTLEMENTS_PAGE_SIZE });
      setSettlements(results);
      setSettlementsPage(1);
      setSettlementsHasMore(results.length === SETTLEMENTS_PAGE_SIZE);
      setSettlementsError(null);
    } catch (err) {
      setSettlementsError(err instanceof Error ? err.message : "Unable to load settlement history.");
    } finally {
      setSettlementsLoading(false);
    }
  }, [accessToken]);

  async function handleLoadMoreSettlements() {
    if (!accessToken || settlementsLoadingMore) return;
    try {
      setSettlementsLoadingMore(true);
      const nextPage = settlementsPage + 1;
      const results = await listRiderSettlements(accessToken, { page: nextPage, limit: SETTLEMENTS_PAGE_SIZE });
      setSettlements((prev) => [...prev, ...results]);
      setSettlementsPage(nextPage);
      setSettlementsHasMore(results.length === SETTLEMENTS_PAGE_SIZE);
    } catch {
      // Leave the list as-is — the rider can retry with another tap.
    } finally {
      setSettlementsLoadingMore(false);
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    await Promise.all([load(), loadSettlements()]);
    setRefreshing(false);
  }

  useFocusEffect(
    useCallback(() => {
      void load();
      void loadSettlements();
    }, [load, loadSettlements]),
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
        <Text style={[styles.title, { color: colors.text }]}>Wallet</Text>
        <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back to dashboard" />
      </View>

      {loading ? (
        <>
          <SkeletonCard />
          <SkeletonCard />
        </>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : wallet ? (
        <>
          <View style={[styles.balanceCard, isNegative(wallet.wallet_balance) && styles.balanceCardNegative]}>
            <Text style={styles.balanceLabel}>Wallet Balance</Text>
            <Text style={styles.balanceAmount}>{rupees(wallet.wallet_balance)}</Text>
            {isNegative(wallet.wallet_balance) && (
              <Text style={styles.balanceHint}>You owe this amount to the platform</Text>
            )}
          </View>

          <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <Text style={[styles.cardLabel, { color: colors.muted }]}>Earnings</Text>
            <Text style={[styles.cardAmount, { color: colors.text }]}>{rupees(wallet.total_earnings)}</Text>
          </View>

          <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <Text style={[styles.cardLabel, { color: colors.muted }]}>COD Collected</Text>
            <Text style={[styles.cardAmount, { color: colors.text }]}>{rupees(wallet.total_cod_collected)}</Text>
            <Text style={[styles.muted, { color: colors.muted }]}>Cash held on the platform&apos;s behalf — not your income</Text>
          </View>

          <View style={styles.statsRow}>
            <View style={[styles.card, styles.statCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
              <Text style={[styles.cardLabel, { color: colors.muted }]}>Settlement Due</Text>
              <Text style={[styles.cardAmount, { color: colors.text }]}>{rupees(wallet.settlement_due)}</Text>
            </View>
            <View style={[styles.card, styles.statCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
              <Text style={[styles.cardLabel, { color: colors.muted }]}>Settled Amount</Text>
              <Text style={[styles.cardAmount, { color: colors.text }]}>{rupees(wallet.total_settled)}</Text>
            </View>
          </View>

          <Text style={[styles.sectionTitle, { color: colors.text }]}>Settlement history</Text>
          {settlementsLoading ? (
            <SkeletonCard />
          ) : settlementsError ? (
            <ErrorState message={settlementsError} onRetry={loadSettlements} />
          ) : settlements.length === 0 ? (
            <EmptyState icon="🧾" message="No settlements recorded yet." />
          ) : (
            <>
              {settlements.map((settlement) => (
                <View
                  key={settlement.id}
                  style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}
                >
                  <View style={styles.settlementRow}>
                    <Text style={[styles.cardLabel, { color: colors.text }]}>
                      {settlementTypeLabel(settlement.settlement_type)}
                    </Text>
                    <Text
                      style={[
                        styles.settlementAmount,
                        { color: settlement.settlement_type === "PAYOUT" ? colors.success : colors.text },
                      ]}
                    >
                      {settlement.settlement_type === "PAYOUT" ? "+" : "-"}
                      {rupees(settlement.amount)}
                    </Text>
                  </View>
                  <Text style={[styles.muted, { color: colors.muted }]}>
                    {new Date(settlement.created_at).toLocaleString()}
                  </Text>
                  {settlement.note && <Text style={[styles.muted, { color: colors.muted }]}>{settlement.note}</Text>}
                </View>
              ))}

              {settlementsHasMore && (
                <Button
                  title={settlementsLoadingMore ? "Loading…" : "Load More"}
                  onPress={handleLoadMoreSettlements}
                  disabled={settlementsLoadingMore}
                  accessibilityLabel="Load more settlement history"
                />
              )}
            </>
          )}
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
  muted: { fontSize: 12, marginTop: 2 },
  balanceCard: {
    padding: 20,
    borderRadius: 12,
    backgroundColor: "#ecfdf5",
    borderWidth: 1,
    borderColor: "#a7f3d0",
    gap: 4,
  },
  balanceCardNegative: {
    backgroundColor: "#fef2f2",
    borderColor: "#fecaca",
  },
  balanceLabel: { fontSize: 14, fontWeight: "600", color: "#065f46" },
  balanceAmount: { fontSize: 32, fontWeight: "800", color: "#065f46" },
  balanceHint: { fontSize: 12, color: "#991b1b" },
  card: {
    padding: 16,
    borderRadius: 10,
    borderWidth: 1,
    gap: 4,
  },
  cardLabel: { fontSize: 14, fontWeight: "600" },
  cardAmount: { fontSize: 22, fontWeight: "800" },
  statsRow: { flexDirection: "row", gap: 12 },
  statCard: { flex: 1 },
  sectionTitle: { fontSize: 16, fontWeight: "700", marginTop: 12 },
  settlementRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  settlementAmount: { fontWeight: "700" },
});
