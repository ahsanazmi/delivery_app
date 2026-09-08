import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import type { ProductCardData } from "@/types/product";
import { rupees } from "@/utils/currency";

type Props = {
  product: ProductCardData;
  quantity?: number;
  onAdd?: () => void;
  onIncrease?: () => void;
  onDecrease?: () => void;
  onPress?: () => void;
};

export function ProductCard({
  product,
  quantity = 0,
  onAdd,
  onIncrease,
  onDecrease,
  onPress,
}: Props) {
  const hasQuantity = quantity > 0;

  return (
    <Pressable
      disabled={!onPress || !product.isAvailable}
      onPress={onPress}
      style={({ pressed }) => [
        styles.card,
        (!product.isAvailable || pressed) && styles.muted,
      ]}
    >
      {product.imageUrl ? (
        <Image source={{ uri: product.imageUrl }} style={styles.image} />
      ) : (
        <View style={[styles.image, styles.fallback]}>
          <Text>🍽️</Text>
        </View>
      )}
      <View style={styles.content}>
        <View style={styles.nameRow}>
          <View style={[styles.vegMark, !product.isVeg && styles.nonVegMark]}>
            <View style={styles.vegDot} />
          </View>
          <Text numberOfLines={1} style={styles.name}>
            {product.name}
          </Text>
        </View>
        <Text style={styles.price}>{rupees(product.price)}</Text>
        {!product.isAvailable && (
          <Text style={styles.unavailable}>Currently unavailable</Text>
        )}

        {product.isAvailable &&
          (hasQuantity ? (
            <View style={styles.qtyBox}>
              <Pressable onPress={onDecrease} style={styles.qtyButton}>
                <Text style={styles.qtyText}>−</Text>
              </Pressable>
              <Text style={styles.qtyValue}>{quantity}</Text>
              <Pressable onPress={onIncrease} style={styles.qtyButton}>
                <Text style={styles.qtyText}>+</Text>
              </Pressable>
            </View>
          ) : (
            <Pressable onPress={onAdd} style={styles.addButton}>
              <Text style={styles.addText}>Add</Text>
            </Pressable>
          ))}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    gap: 12,
    padding: 12,
    borderRadius: 14,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  muted: { opacity: 0.58 },
  image: { width: 72, height: 72, borderRadius: 10 },
  fallback: {
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FFE4D6",
  },
  content: { flex: 1, justifyContent: "center", gap: 6 },
  nameRow: { flexDirection: "row", gap: 7, alignItems: "center" },
  name: { flex: 1, color: "#241913", fontWeight: "800", fontSize: 15 },
  price: { color: "#5F5049", fontWeight: "700" },
  vegMark: {
    width: 13,
    height: 13,
    borderWidth: 1,
    borderColor: "#18864B",
    alignItems: "center",
    justifyContent: "center",
  },
  nonVegMark: { borderColor: "#C43E2F" },
  vegDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#18864B" },
  unavailable: { color: "#B42318", fontSize: 12, fontWeight: "700" },
  addButton: {
    alignSelf: "flex-start",
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  addText: { color: "#fff", fontWeight: "800" },
  qtyBox: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    borderRadius: 10,
    backgroundColor: "#FFF0E8",
    overflow: "hidden",
  },
  qtyButton: {
    width: 28,
    height: 28,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FFE4D6",
  },
  qtyText: { color: "#241913", fontSize: 18, fontWeight: "700" },
  qtyValue: {
    minWidth: 24,
    textAlign: "center",
    color: "#241913",
    fontWeight: "800",
    paddingHorizontal: 8,
  },
});
