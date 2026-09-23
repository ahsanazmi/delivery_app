import { useEffect, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { ApiError } from "@/services/api/apiClient";
import {
    createOrderReview,
    getOrderReview,
    updateOrderReview,
    type OrderReview,
} from "@/services/api/reviewsApi";

type Props = {
  accessToken: string;
  orderId: string;
};

export function OrderReviewSection({ accessToken, orderId }: Props) {
  const [review, setReview] = useState<OrderReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [restaurantRating, setRestaurantRating] = useState(0);
  const [deliveryRating, setDeliveryRating] = useState(0);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getOrderReview(accessToken, orderId)
      .then((data) => {
        if (cancelled) return;
        setReview(data);
        if (data) {
          setRestaurantRating(data.restaurant_rating);
          setDeliveryRating(data.delivery_rating);
          setComment(data.comment ?? "");
        }
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [accessToken, orderId]);

  async function handleSubmit() {
    if (restaurantRating === 0 || deliveryRating === 0) {
      Alert.alert("Rating required", "Please rate both the restaurant and the delivery.");
      return;
    }
    setSaving(true);
    try {
      if (review) {
        const updated = await updateOrderReview(accessToken, review.id, {
          restaurant_rating: restaurantRating,
          delivery_rating: deliveryRating,
          comment: comment.trim() || null,
        });
        setReview(updated);
      } else {
        const created = await createOrderReview(accessToken, orderId, {
          restaurant_rating: restaurantRating,
          delivery_rating: deliveryRating,
          comment: comment.trim() || null,
        });
        setReview(created);
      }
      setEditing(false);
    } catch (error) {
      Alert.alert(
        "Unable to save review",
        error instanceof ApiError ? error.message : "Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) return null;

  const showForm = !review || editing;

  return (
    <View style={styles.card}>
      <Text style={styles.sectionTitle}>{review ? "Your review" : "Rate your order"}</Text>

      {showForm ? (
        <>
          <StarRow label="Restaurant" value={restaurantRating} onChange={setRestaurantRating} />
          <StarRow label="Delivery" value={deliveryRating} onChange={setDeliveryRating} />
          <TextInput
            placeholder="Add a comment (optional)"
            placeholderTextColor="#8A7267"
            value={comment}
            onChangeText={setComment}
            style={styles.input}
            multiline
          />
          <Pressable style={styles.submitButton} onPress={handleSubmit} disabled={saving}>
            <Text style={styles.submitText}>
              {saving ? "Saving…" : review ? "Update review" : "Submit review"}
            </Text>
          </Pressable>
          {review && (
            <Pressable style={styles.cancelEditButton} onPress={() => setEditing(false)}>
              <Text style={styles.cancelEditText}>Cancel</Text>
            </Pressable>
          )}
        </>
      ) : (
        <>
          <StarRow label="Restaurant" value={review.restaurant_rating} readOnly />
          <StarRow label="Delivery" value={review.delivery_rating} readOnly />
          {review.comment ? <Text style={styles.commentText}>{review.comment}</Text> : null}
          <Pressable style={styles.editButton} onPress={() => setEditing(true)}>
            <Text style={styles.editText}>Edit review</Text>
          </Pressable>
        </>
      )}
    </View>
  );
}

function StarRow({
  label,
  value,
  onChange,
  readOnly,
}: {
  label: string;
  value: number;
  onChange?: (value: number) => void;
  readOnly?: boolean;
}) {
  return (
    <View style={styles.starRow}>
      <Text style={styles.starLabel}>{label}</Text>
      <View style={styles.starsWrap}>
        {[1, 2, 3, 4, 5].map((n) => (
          <Pressable key={n} disabled={readOnly} onPress={() => onChange?.(n)}>
            <Text style={[styles.star, n <= value && styles.starFilled]}>★</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  sectionTitle: { color: "#241913", fontWeight: "800", fontSize: 15, marginBottom: 10 },
  starRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  starLabel: { color: "#5F5049", fontWeight: "700" },
  starsWrap: { flexDirection: "row", gap: 4 },
  star: { fontSize: 22, color: "#EADDD6" },
  starFilled: { color: "#FF9F1C" },
  input: {
    backgroundColor: "#FFF8F5",
    borderColor: "#EADDD6",
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    marginTop: 4,
    marginBottom: 12,
    color: "#241913",
    minHeight: 60,
    textAlignVertical: "top",
  },
  submitButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  submitText: { color: "#fff", fontWeight: "800" },
  cancelEditButton: { marginTop: 10, alignItems: "center" },
  cancelEditText: { color: "#8A7267", fontWeight: "700" },
  commentText: { color: "#5F5049", marginTop: 6, marginBottom: 10, lineHeight: 20 },
  editButton: {
    marginTop: 4,
    alignSelf: "flex-start",
    backgroundColor: "#FFF0E8",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  editText: { color: "#D83B05", fontWeight: "800", fontSize: 13 },
});
