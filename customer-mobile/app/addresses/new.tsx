import { Redirect, useRouter } from "expo-router";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AddressForm } from "@/features/addresses/AddressForm";
import { useSession } from "@/features/auth/session-context";
import { createAddress } from "@/services/api/addressesApi";

export default function NewAddressScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();

  if (!user || !accessToken) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Add address</Text>
      </View>
      <ScrollView contentContainerStyle={styles.content}>
        <AddressForm
          submitLabel="Save address"
          onSubmit={async (payload) => {
            await createAddress(accessToken, payload);
            router.back();
          }}
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  headerRow: { paddingHorizontal: 18, paddingTop: 16, paddingBottom: 8 },
  title: { fontSize: 24, fontWeight: "800", color: "#241913" },
  content: { padding: 20, paddingBottom: 40 },
});
