import { useRouter } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

const roleOptions = [
  {
    title: "Customer",
    subtitle: "Browse restaurants and place orders",
    route: "/login",
  },
  {
    title: "Admin",
    subtitle: "Manage orders, riders and restaurant activity",
    route: "/admin/login",
  },
  {
    title: "Rider",
    subtitle: "View deliveries and update order status",
    route: "/rider/login",
  },
  {
    title: "Restaurant",
    subtitle: "Manage your restaurant profile and menu",
    route: "/restaurant/login",
  },
] as const;

export default function RolePortalScreen() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.eyebrow}>Say Hi Chai</Text>
        <Text style={styles.title}>Choose your portal</Text>
        <Text style={styles.subtitle}>
          Sign in to the role that matches your work or customer journey.
        </Text>

        {roleOptions.map((option) => (
          <Pressable
            key={option.title}
            accessibilityRole="button"
            onPress={() => router.push(option.route)}
            style={({ pressed }) => [
              styles.card,
              pressed && styles.cardPressed,
            ]}
          >
            <Text style={styles.cardTitle}>{option.title}</Text>
            <Text style={styles.cardSubtitle}>{option.subtitle}</Text>
            <Text style={styles.cardAction}>Open portal →</Text>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  container: {
    flexGrow: 1,
    paddingHorizontal: 20,
    paddingVertical: 28,
    justifyContent: "center",
    gap: 16,
  },
  eyebrow: {
    color: "#FF5A1F",
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 1.2,
    textTransform: "uppercase",
  },
  title: {
    color: "#17120F",
    fontSize: 30,
    fontWeight: "800",
    letterSpacing: -0.7,
  },
  subtitle: {
    color: "#6D625D",
    fontSize: 16,
    marginBottom: 12,
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#F3E5DC",
    padding: 18,
    shadowColor: "#000",
    shadowOpacity: 0.04,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  },
  cardPressed: {
    backgroundColor: "#FFF3EE",
  },
  cardTitle: {
    color: "#17120F",
    fontSize: 22,
    fontWeight: "700",
  },
  cardSubtitle: {
    color: "#5B504B",
    fontSize: 14,
    marginTop: 6,
    lineHeight: 20,
  },
  cardAction: {
    color: "#FF5A1F",
    marginTop: 12,
    fontSize: 14,
    fontWeight: "800",
  },
});
