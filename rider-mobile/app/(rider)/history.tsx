import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { Button, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/SkeletonBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { listRiderHistory, type RiderHistoryItem } from "@/services/api/historyApi";
import { useAuthStore } from "@/store/authStore";
import { rupees } from "@/utils/currency";

const PAGE_SIZE = 20;

type Bucket = "Today" | "Yesterday" | "Previous Deliveries";

function bucketFor(dateIso: string): Bucket {
  const date = new Date(dateIso);
  const now = new Date();
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  return "Previous Deliveries";
}

export default function RiderHistoryScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [items, setItems] = useState<RiderHistoryItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    try {
      const results = await listRiderHistory(accessToken, { page: 1, limit: PAGE_SIZE });
      setItems(results);
      setPage(1);
      setHasMore(results.length === PAGE_SIZE);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load delivery history.");
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

  async function handleLoadMore() {
    if (!accessToken || loadingMore) return;
    try {
      setLoadingMore(true);
      const nextPage = page + 1;
      const results = await listRiderHistory(accessToken, { page: nextPage, limit: PAGE_SIZE });
      setItems((prev) => [...prev, ...results]);
      setPage(nextPage);
      setHasMore(results.length === PAGE_SIZE);
    } catch {
      // Leave the list as-is — the user can retry with another tap.
    } finally {
      setLoadingMore(false);
    }
  }

  const sections = useMemo(() => {
    const grouped: Record<Bucket, RiderHistoryItem[]> = {
      Today: [],
      Yesterday: [],
      "Previous Deliveries": [],
    };
    for (const item of items) {
      grouped[bucketFor(item.date)].push(item);
    }
    return (["Today", "Yesterday", "Previous Deliveries"] as Bucket[])
      .map((bucket) => ({ bucket, records: grouped[bucket] }))
      .filter((section) => section.records.length > 0);
  }, [items]);

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
        <Text style={[styles.title, { color: colors.text }]}>Delivery History</Text>
        <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back to dashboard" />
      </View>

      {loading ? (
        <>
          <SkeletonCard />
          <SkeletonCard />
        </>
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState icon="🧾" message="No completed deliveries yet." />
      ) : (
        <>
          {sections.map((section) => (
            <View key={section.bucket} style={styles.section}>
              <Text style={[styles.sectionTitle, { color: colors.text }]}>{section.bucket}</Text>
              {section.records.map((item) => (
                <TouchableOpacity
                  key={item.order_id}
                  style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}
                  onPress={() => router.push({ pathname: "/delivery/[id]", params: { id: item.order_id } })}
                  accessibilityRole="button"
                  accessibilityLabel={`Order ${item.order_number} from ${item.restaurant_name}, ${item.status}`}
                >
                  <View style={styles.cardRow}>
                    <Text style={[styles.orderNumber, { color: colors.text }]}>{item.order_number}</Text>
                    <StatusBadge status={item.status} />
                  </View>
                  <Text style={[styles.restaurant, { color: colors.text }]}>{item.restaurant_name}</Text>
                  <Text style={[styles.muted, { color: colors.muted }]}>{new Date(item.date).toLocaleString()}</Text>
                  <View style={styles.cardRow}>
                    <Text style={[styles.earning, { color: colors.success }]}>Earned {rupees(item.earning)}</Text>
                    <Text style={[styles.muted, { color: colors.muted }]}>{item.payment_method.toUpperCase()}</Text>
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          ))}

          {hasMore && (
            <Button
              title={loadingMore ? "Loading…" : "Load More"}
              onPress={handleLoadMore}
              disabled={loadingMore}
              accessibilityLabel="Load more delivery history"
            />
          )}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  container: { padding: 24, gap: 12, flexGrow: 1 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 24, fontWeight: "700" },
  muted: { fontSize: 13 },
  section: { gap: 8 },
  sectionTitle: { fontSize: 16, fontWeight: "700", marginTop: 12 },
  card: {
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    gap: 4,
  },
  cardRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  orderNumber: { fontWeight: "700", fontSize: 15 },
  restaurant: { fontSize: 14 },
  earning: { fontWeight: "700" },
});
