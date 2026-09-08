import { Redirect, useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";

export default function SplashScreen() {
  const { user, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated" && user) {
      const timeout = setTimeout(() => router.replace("/home"), 700);
      return () => clearTimeout(timeout);
    }

    if (status === "anonymous") {
      const timeout = setTimeout(() => router.replace("/portal"), 1200);
      return () => clearTimeout(timeout);
    }
  }, [router, status, user]);

  if (status === "authenticated" && user) {
    return <Redirect href="/home" />;
  }

  if (status === "anonymous") {
    return (
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.container}>
          <View style={styles.brandMark}>
            <Text style={styles.brandCup}>☕</Text>
            <Text style={styles.brandSteam}>~</Text>
          </View>
          <Text style={styles.title}>Say Hi Chai</Text>
          <Text style={styles.subtitle}>
            Fresh food, fast delivery, local favourites.
          </Text>
          <ActivityIndicator
            size="large"
            color="#FF5A1F"
            style={styles.loader}
          />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.brandMark}>
          <Text style={styles.brandCup}>☕</Text>
          <Text style={styles.brandSteam}>~</Text>
        </View>
        <Text style={styles.title}>Say Hi Chai</Text>
        <Text style={styles.subtitle}>
          Fresh food, fast delivery, local favourites.
        </Text>
        <ActivityIndicator size="large" color="#FF5A1F" style={styles.loader} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  container: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 24,
  },
  brandMark: {
    width: 100,
    height: 100,
    borderRadius: 28,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 22,
    shadowColor: "#000",
    shadowOpacity: 0.08,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  brandCup: { fontSize: 42 },
  brandSteam: {
    position: "absolute",
    top: -8,
    left: "50%",
    transform: [{ translateX: -10 }],
    color: "#fff",
    fontSize: 32,
    fontWeight: "800",
  },
  title: {
    color: "#241913",
    fontSize: 32,
    fontWeight: "800",
    letterSpacing: -0.8,
  },
  subtitle: {
    color: "#6D625D",
    fontSize: 16,
    marginTop: 10,
    textAlign: "center",
  },
  loader: { marginTop: 24 },
  button: {
    marginTop: 24,
    backgroundColor: "#FF5A1F",
    borderRadius: 12,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  buttonText: { color: "#fff", fontSize: 15, fontWeight: "800" },
});
