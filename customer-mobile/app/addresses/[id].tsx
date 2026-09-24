import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AddressForm } from "@/features/addresses/AddressForm";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { getAddress, updateAddress, type Address } from "@/services/api/addressesApi";

export default function EditAddressScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, accessToken } = useSession();
  const [address, setAddress] = useState<Address | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accessToken || !id) return;
    getAddress(accessToken, id)
      .then(setAddress)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : "Unable to load address."))
      .finally(() => setLoading(false));
  }, [accessToken, id]);

  if (!user || !accessToken) return <Redirect href="/login" />;
  if (!id) return <Redirect href="/addresses" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Edit address</Text>
      </View>
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error || !address ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error ?? "Address not found."}</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          <AddressForm
            initialValues={address}
            submitLabel="Save changes"
            onSubmit={async (payload) => {
              await updateAddress(accessToken, address.id, payload);
              router.back();
            }}
          />
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  headerRow: { paddingHorizontal: 18, paddingTop: 16, paddingBottom: 8 },
  title: { fontSize: 24, fontWeight: "800", color: "#241913" },
  content: { padding: 20, paddingBottom: 40 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", lineHeight: 21 },
});
