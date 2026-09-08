import type { Restaurant } from "@/services/api/restaurantsApi";
import { StyleSheet, Text, View } from "react-native";

export default function RestaurantCard({
  restaurant,
}: {
  restaurant: Restaurant;
}) {
  return (
    <View style={styles.card}>
      <Text style={styles.name}>{restaurant.name}</Text>
      <Text style={styles.meta}>
        Rating: {Number(restaurant.average_rating).toFixed(1)} • Delivery: ₹
        {Number(restaurant.delivery_fee).toFixed(0)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 12,
    marginVertical: 6,
    marginHorizontal: 12,
    backgroundColor: "#fff",
    borderRadius: 8,
    elevation: 2,
  },
  name: { fontSize: 16, fontWeight: "600" },
  meta: { fontSize: 12, color: "#666", marginTop: 4 },
});
