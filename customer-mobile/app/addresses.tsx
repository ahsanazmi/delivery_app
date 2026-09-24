import { Redirect, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import {
    deleteAddress,
    listAddresses,
    setDefaultAddress,
    type Address,
} from "@/services/api/addressesApi";

// Maps & Location System Phase 5 — Customer Address Management. The
// standalone "manage my saved addresses" surface — distinct from
// checkout's own inline address selection/creation, which already
// existed before this phase. This is where edit/delete/set-default
// actually live, since checkout never supported those.

export default function AddressesScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setError(null);
    try {
      setAddresses(await listAddresses(accessToken));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load addresses.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function handleSetDefault(address: Address) {
    if (!accessToken || address.is_default) return;
    setBusyId(address.id);
    try {
      await setDefaultAddress(accessToken, address.id);
      await load();
    } catch (caught) {
      Alert.alert("Unable to update", caught instanceof ApiError ? caught.message : "Please try again.");
    } finally {
      setBusyId(null);
    }
  }

  function handleDelete(address: Address) {
    Alert.alert("Delete address", `Remove "${address.label}"?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          if (!accessToken) return;
          setBusyId(address.id);
          try {
            await deleteAddress(accessToken, address.id);
            await load();
          } catch (caught) {
            Alert.alert("Unable to delete", caught instanceof ApiError ? caught.message : "Please try again.");
          } finally {
            setBusyId(null);
          }
        },
      },
    ]);
  }

  if (!user || !accessToken) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>My addresses</Text>
        <View style={styles.headerSpacer} />
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
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          {addresses.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.emptyEmoji}>📍</Text>
              <Text style={styles.emptyTitle}>No saved addresses</Text>
              <Text style={styles.emptyCopy}>Add an address to speed up checkout.</Text>
            </View>
          ) : (
            addresses.map((address) => (
              <View key={address.id} style={styles.card}>
                <View style={styles.rowBetween}>
                  <Text style={styles.label}>{address.label}</Text>
                  {address.is_default && (
                    <Text style={styles.defaultBadge}>Default</Text>
                  )}
                </View>
                <Text style={styles.recipient}>{address.recipient_name} · {address.phone}</Text>
                <Text style={styles.addressLine}>
                  {address.address_line}
                  {address.landmark ? `, ${address.landmark}` : ""}
                </Text>
                <Text style={styles.addressLine}>
                  {[address.city, address.district, address.state].filter(Boolean).join(", ")} - {address.postal_code}
                </Text>

                <View style={styles.actionsRow}>
                  {!address.is_default && (
                    <Pressable
                      style={styles.actionButton}
                      onPress={() => handleSetDefault(address)}
                      disabled={busyId === address.id}
                    >
                      <Text style={styles.actionText}>Set default</Text>
                    </Pressable>
                  )}
                  <Pressable
                    style={styles.actionButton}
                    onPress={() => router.push({ pathname: "/addresses/[id]", params: { id: address.id } })}
                  >
                    <Text style={styles.actionText}>Edit</Text>
                  </Pressable>
                  <Pressable
                    style={styles.actionButton}
                    onPress={() => handleDelete(address)}
                    disabled={busyId === address.id}
                  >
                    <Text style={styles.deleteText}>Delete</Text>
                  </Pressable>
                </View>
              </View>
            ))
          )}

          <Pressable style={styles.addButton} onPress={() => router.push("/addresses/new")}>
            <Text style={styles.addButtonText}>+ Add new address</Text>
          </Pressable>
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
  label: { color: "#241913", fontWeight: "800", fontSize: 16 },
  defaultBadge: {
    color: "#157347",
    backgroundColor: "#E8F6EE",
    fontSize: 12,
    fontWeight: "800",
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  recipient: { color: "#6D625D", marginTop: 8 },
  addressLine: { color: "#241913", marginTop: 4, lineHeight: 20 },
  actionsRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 14,
  },
  actionButton: {
    borderWidth: 1,
    borderColor: "#F0E3DC",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  actionText: { color: "#D83B05", fontWeight: "700", fontSize: 13 },
  deleteText: { color: "#B42318", fontWeight: "700", fontSize: 13 },
  addButton: {
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: "#D83B05",
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: "center",
  },
  addButtonText: { color: "#D83B05", fontWeight: "800" },
  emptyState: { alignItems: "center", justifyContent: "center", paddingTop: 60 },
  emptyEmoji: { fontSize: 48 },
  emptyTitle: { color: "#241913", fontSize: 22, fontWeight: "800", marginTop: 12 },
  emptyCopy: { color: "#6D625D", textAlign: "center", lineHeight: 22, marginTop: 8 },
});
