import { Link } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

export default function VerifyScreen() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>Verify your account</Text>
        <Text style={styles.body}>
          This step is reserved for OTP email/phone verification before the
          customer can place orders.
        </Text>
        <Link href="/login" style={styles.link}>
          Back to sign in
        </Link>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  container: { flex: 1, justifyContent: "center", paddingHorizontal: 24 },
  title: { fontSize: 28, fontWeight: "800", marginBottom: 12 },
  body: { fontSize: 16, lineHeight: 24, color: "#4B3F3A", marginBottom: 20 },
  link: { color: "#D83B05", fontWeight: "700", fontSize: 16 },
});
