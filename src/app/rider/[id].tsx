import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Button,
    Linking,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { useSession } from "@/features/auth/session-context";
import {
    listRiderOrders,
    markOrderDelivered,
    markOrderPickedUp,
    type RiderOrder,
} from "@/services/api/riderApi";

export default function RiderDeliveryDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { accessToken, user, signOut } = useSession();
  const [order, setOrder] = useState<RiderOrder | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!accessToken || !id) return;
    void (async () => {
      try {
        const orders = await listRiderOrders(accessToken);
        const match = orders.find((entry) => entry.id === id) ?? null;
        setOrder(match);
      } finally {
        setLoading(false);
      }
    })();
  }, [accessToken, id]);

  const customerPhone = order?.user_id ? "+923001234567" : null;

  async function handlePickUp() {
    if (!accessToken || !order) return;
    const nextOrder = await markOrderPickedUp(accessToken, order.id);
    setOrder(nextOrder);
  }

  async function handleDeliver() {
    if (!accessToken || !order) return;
    const nextOrder = await markOrderDelivered(accessToken, order.id);
    setOrder(nextOrder);
  }

  if (!user || !accessToken) {
    return (
      <View style={styles.centered}>
        <Text>Please log in to continue.</Text>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!order) {
    return (
      <View style={styles.centered}>
        <Text>Delivery not found.</Text>
        <Button
          title="Back to orders"
          onPress={() => router.replace("/rider")}
        />
      </View>
    );
  }

  const mapUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${order.address_line}, ${order.city}`)}`;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Current Delivery</Text>
      <Text style={styles.orderNumber}>{order.order_number}</Text>
      <Text style={styles.label}>Pickup restaurant</Text>
      <Text>{order.restaurant_name ?? "Restaurant"}</Text>
      <Text style={styles.muted}>Status: {order.status}</Text>

      <Text style={styles.label}>Customer address</Text>
      <Text>{order.address_line}</Text>
      <Text>
        {order.city}, {order.postal_code}
      </Text>
      <Text>{order.delivery_instructions ?? "No instructions"}</Text>

      <View style={styles.buttonGroup}>
        <Button
          title="Call Customer"
          onPress={() => {
            if (customerPhone) void Linking.openURL(`tel:${customerPhone}`);
            else Alert.alert("No number available");
          }}
        />
        <Button
          title="Open Google Maps"
          onPress={() => void Linking.openURL(mapUrl)}
        />
        <Button title="Mark Picked Up" onPress={handlePickUp} />
        <Button title="Mark Delivered" onPress={handleDeliver} />
        <Button title="Delivery History" onPress={() => router.back()} />
      </View>

      <Button
        title="Logout"
        onPress={() => {
          signOut();
          router.replace("/rider/login");
        }}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  container: { padding: 24, gap: 12 },
  title: { fontSize: 28, fontWeight: "700" },
  orderNumber: { fontSize: 18, fontWeight: "700" },
  label: { fontSize: 16, fontWeight: "700", marginTop: 8 },
  muted: { color: "#4b5563" },
  buttonGroup: { gap: 10, marginTop: 12 },
});
