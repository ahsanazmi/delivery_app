import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Button, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { ErrorState } from "@/components/ErrorState";
import { useThemeColors } from "@/hooks/use-theme-colors";
import { useAuthStore } from "@/store/authStore";
import { useRiderStore } from "@/store/riderStore";

const STEPS = [
  { key: "submitted", label: "Application Submitted" },
  { key: "review", label: "Under Review" },
  { key: "approved", label: "Approved" },
] as const;

export default function RiderVerificationScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const accessToken = useAuthStore((state) => state.accessToken);
  const signOut = useAuthStore((state) => state.signOut);
  const verification = useRiderStore((state) => state.verification);
  const fetchVerification = useRiderStore((state) => state.fetchVerification);
  const resubmitVerification = useRiderStore((state) => state.resubmitVerification);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [resubmitting, setResubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh = false) => {
      if (!accessToken) return;
      if (isRefresh) setRefreshing(true);
      setError(null);
      try {
        await fetchVerification(accessToken);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load your verification status.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [accessToken, fetchVerification],
  );

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function handleResubmit() {
    if (!accessToken) return;
    setResubmitting(true);
    setError(null);
    try {
      await resubmitVerification(accessToken);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to resubmit your application.");
    } finally {
      setResubmitting(false);
    }
  }

  async function handleLogout() {
    await signOut();
    router.replace("/login");
  }

  if (loading) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  const status = verification?.approval_status ?? "PENDING";

  return (
    <ScrollView
      contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} />}
    >
      <Text style={[styles.title, { color: colors.text }]}>Rider verification</Text>

      {(status === "PENDING" || status === "APPROVED") && (
        <View style={styles.stepTrack}>
          {STEPS.map((step, index) => {
            const currentIndex = status === "APPROVED" ? STEPS.length - 1 : 1; // PENDING = "Under Review"
            const done = index <= currentIndex;
            return (
              <View key={step.key} style={styles.step}>
                <View style={[styles.stepDot, { backgroundColor: done ? colors.primary : colors.skeleton }]} />
                <Text style={[styles.stepLabel, { color: done ? colors.text : colors.muted, fontWeight: done ? "600" : "400" }]}>
                  {step.label}
                </Text>
              </View>
            );
          })}
        </View>
      )}

      {status === "PENDING" && (
        <>
          <Text style={[styles.body, { color: colors.muted }]}>
            Your application is under review. This usually takes 1-2 business days — check back here for updates.
          </Text>
          <Button title="Manage documents" onPress={() => router.push("/documents")} accessibilityLabel="Manage documents" />
          <Button title="Vehicle information" onPress={() => router.push("/vehicle")} accessibilityLabel="Vehicle information" />
        </>
      )}

      {status === "APPROVED" && (
        <>
          <Text style={[styles.body, { color: colors.muted }]}>You&apos;re approved! You can now accept deliveries.</Text>
          <Button title="Continue" onPress={() => router.replace("/")} accessibilityLabel="Continue to dashboard" />
        </>
      )}

      {status === "REJECTED" && (
        <View style={styles.rejectedCard}>
          <Text style={styles.rejectedTitle}>Application rejected</Text>
          <Text style={styles.body}>{verification?.rejection_reason || "No reason was provided."}</Text>
          <Button title="Manage documents" onPress={() => router.push("/documents")} accessibilityLabel="Manage documents" />
          <Button title="Vehicle information" onPress={() => router.push("/vehicle")} accessibilityLabel="Vehicle information" />
          <Button
            title={resubmitting ? "Resubmitting..." : "Resubmit application"}
            onPress={handleResubmit}
            disabled={resubmitting}
            accessibilityLabel="Resubmit application"
          />
        </View>
      )}

      {status === "SUSPENDED" && (
        <View style={styles.rejectedCard}>
          <Text style={styles.rejectedTitle}>Account suspended</Text>
          <Text style={styles.body}>
            Your delivery-partner account has been suspended. Contact support for more information.
          </Text>
        </View>
      )}

      {error ? <ErrorState message={error} onRetry={() => load()} /> : null}

      <Button
        title={refreshing ? "Refreshing..." : "Refresh status"}
        onPress={() => load(true)}
        disabled={refreshing}
        accessibilityLabel="Refresh verification status"
      />
      <Button title="Logout" onPress={handleLogout} color={colors.danger} accessibilityLabel="Log out" />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center" },
  container: { flexGrow: 1, justifyContent: "center", paddingHorizontal: 24, paddingVertical: 32, gap: 16 },
  title: { fontSize: 26, fontWeight: "700" },
  body: { fontSize: 15, lineHeight: 22, color: "#4b5563" },
  stepTrack: { gap: 12 },
  step: { flexDirection: "row", alignItems: "center", gap: 10 },
  stepDot: { width: 12, height: 12, borderRadius: 6 },
  stepLabel: { fontSize: 15 },
  rejectedCard: {
    borderWidth: 1,
    borderColor: "#fecaca",
    backgroundColor: "#fef2f2",
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  rejectedTitle: { fontSize: 17, fontWeight: "700", color: "#b91c1c" },
});
