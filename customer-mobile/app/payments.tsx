import { Redirect, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
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
    listPaymentHistory,
    type CustomerPaymentHistoryEntry,
} from "@/services/api/paymentsApi";
import { rupees } from "@/utils/currency";
import { paymentStatusMeta } from "@/utils/paymentStatus";

const PAGE_SIZE = 20;

export default function PaymentHistoryScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const [payments, setPayments] = useState<CustomerPaymentHistoryEntry[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFirstPage = useCallback(async () => {
    if (!accessToken) return;
    setError(null);
    try {
      const data = await listPaymentHistory(accessToken, { page: 1, limit: PAGE_SIZE });
      setPayments(data);
      setPage(1);
      setHasMore(data.length === PAGE_SIZE);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load payment history.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [accessToken]);

  // Same reasoning as the orders list (Phase 19) — refetches on every
  // focus, not just first mount, so returning here after a retry/refund
  // always shows the current status.
  useFocusEffect(
    useCallback(() => {
      void loadFirstPage();
    }, [loadFirstPage]),
  );

  async function loadMore() {
    if (!accessToken || loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const data = await listPaymentHistory(accessToken, { page: nextPage, limit: PAGE_SIZE });
      setPayments((current) => [...current, ...data]);
      setPage(nextPage);
      setHasMore(data.length === PAGE_SIZE);
    } catch {
      // keep whatever's already loaded; the user can pull to refresh instead
    } finally {
      setLoadingMore(false);
    }
  }

  function handleRefresh() {
    setRefreshing(true);
    loadFirstPage();
  }

  if (!user || !accessToken) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Payment history</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.retryButton} onPress={loadFirstPage}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : payments.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyEmoji}>🧾</Text>
          <Text style={styles.emptyTitle}>No payments yet</Text>
          <Text style={styles.emptyCopy}>
            Payments for your orders will show up here once you place one.
          </Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor="#FF5A1F" />}
        >
          {payments.map((payment) => (
            <PaymentCard
              key={payment.payment_id}
              payment={payment}
              onPress={() => router.push({ pathname: "/orders/[id]", params: { id: payment.order_id } })}
            />
          ))}

          {hasMore && (
            <Pressable style={styles.loadMoreButton} onPress={loadMore} disabled={loadingMore}>
              <Text style={styles.loadMoreText}>{loadingMore ? "Loading…" : "Load more"}</Text>
            </Pressable>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function PaymentCard({
  payment,
  onPress,
}: {
  payment: CustomerPaymentHistoryEntry;
  onPress: () => void;
}) {
  const meta = paymentStatusMeta(payment.status);
  return (
    <Pressable style={styles.card} onPress={onPress}>
      <View style={styles.rowBetween}>
        <Text style={styles.orderNumber}>{payment.order_number}</Text>
        <Text
          style={[
            styles.status,
            { backgroundColor: meta.backgroundColor, color: meta.color },
          ]}
        >
          {meta.label}
        </Text>
      </View>
      <View style={styles.rowBetween}>
        <Text style={styles.label}>{payment.method === "cod" ? "Cash on delivery" : "Paid online"}</Text>
        <Text style={styles.total}>{rupees(payment.amount)}</Text>
      </View>
      <Text style={styles.date}>
        {new Date(payment.created_at).toLocaleString()}
      </Text>
    </Pressable>
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
  title: { fontSize: 24, fontWeight: "800", color: "#241913" },
  headerSpacer: { width: 40 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", marginBottom: 14, lineHeight: 21 },
  retryButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
  content: { padding: 20, paddingBottom: 40, gap: 14 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    padding: 16,
  },
  rowBetween: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  orderNumber: { color: "#241913", fontWeight: "800", fontSize: 16 },
  status: {
    fontSize: 12,
    fontWeight: "800",
    borderRadius: 999,
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  label: { color: "#6D625D", marginTop: 10 },
  total: { color: "#D83B05", fontWeight: "800", marginTop: 10 },
  date: { color: "#8A7C74", marginTop: 8 },
  loadMoreButton: {
    alignSelf: "center",
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  loadMoreText: { color: "#D83B05", fontWeight: "800" },
  emptyState: {
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 80,
  },
  emptyEmoji: { fontSize: 48 },
  emptyTitle: {
    color: "#241913",
    fontSize: 22,
    fontWeight: "800",
    marginTop: 12,
  },
  emptyCopy: {
    color: "#6D625D",
    textAlign: "center",
    lineHeight: 22,
    marginTop: 8,
  },
});
