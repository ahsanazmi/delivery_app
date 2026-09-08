import { Redirect, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
    Alert,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import {
    createAddress,
    listAddresses,
    type Address,
} from "@/services/api/addressesApi";
import { createOrder } from "@/services/api/ordersApi";
import { rupees } from "@/utils/currency";

const emptyForm = {
  label: "Home",
  recipientName: "",
  phone: "",
  addressLine: "",
  city: "",
  state: "",
  postalCode: "",
  landmark: "",
  latitude: "",
  longitude: "",
  deliveryInstructions: "",
};

export default function CheckoutScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const { items, subtotal, clearCart } = useCart();
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [selectedAddressId, setSelectedAddressId] = useState<string | null>(
    null,
  );
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!user || !accessToken) return;
    const loadAddresses = async () => {
      try {
        setLoading(true);
        const nextAddresses = await listAddresses(accessToken);
        setAddresses(nextAddresses);
        const fallback =
          nextAddresses.find((address) => address.is_default) ??
          nextAddresses[0] ??
          null;
        setSelectedAddressId(fallback?.id ?? null);
      } catch (error) {
        setAddresses([]);
        setSelectedAddressId(null);
      } finally {
        setLoading(false);
      }
    };

    loadAddresses();
  }, [accessToken, user]);

  const selectedAddress = useMemo(
    () => addresses.find((address) => address.id === selectedAddressId) ?? null,
    [addresses, selectedAddressId],
  );

  const orderSummary = subtotal + 0;

  if (!user || !accessToken) return <Redirect href="/login" />;

  async function requestCurrentLocation() {
    if (typeof navigator !== "undefined" && "geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setForm((current) => ({
            ...current,
            latitude: String(position.coords.latitude),
            longitude: String(position.coords.longitude),
          }));
        },
        () => {
          Alert.alert(
            "Location unavailable",
            "Please enter your delivery details manually.",
          );
        },
        { enableHighAccuracy: true },
      );
      return;
    }

    Alert.alert(
      "Location access",
      "Location can be detected on device builds. For now, enter the address manually.",
    );
  }

  async function saveAddress() {
    if (!accessToken) {
      Alert.alert(
        "Authentication required",
        "Please log in before saving an address.",
      );
      return;
    }

    if (
      !form.addressLine ||
      !form.city ||
      !form.state ||
      !form.postalCode ||
      !form.recipientName ||
      !form.phone
    ) {
      Alert.alert(
        "Incomplete address",
        "Please fill in the delivery details before saving.",
      );
      return;
    }

    try {
      setSaving(true);
      const nextAddress = await createAddress(accessToken, {
        label: form.label || "Home",
        recipient_name: form.recipientName,
        phone: form.phone,
        address_line: form.addressLine,
        city: form.city,
        state: form.state,
        postal_code: form.postalCode,
        landmark: form.landmark || null,
        latitude: form.latitude ? Number(form.latitude) : null,
        longitude: form.longitude ? Number(form.longitude) : null,
      });
      setAddresses((current) => [nextAddress, ...current]);
      setSelectedAddressId(nextAddress.id);
      setForm((current) => ({
        ...current,
        label: "Home",
        landmark: "",
        latitude: "",
        longitude: "",
      }));
      Alert.alert(
        "Address saved",
        "Your delivery address is ready for checkout.",
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to save the address.";
      Alert.alert("Address error", message);
    } finally {
      setSaving(false);
    }
  }

  async function placeOrder() {
    if (!accessToken) {
      Alert.alert(
        "Authentication required",
        "Please log in before placing an order.",
      );
      return;
    }

    if (items.length === 0) {
      Alert.alert("Empty cart", "Add items before placing an order.");
      return;
    }

    const orderPayload = {
      restaurant_name: items[0]?.restaurantName ?? "Say Hi Chai",
      restaurant_phone: user?.phone ?? null,
      address_line: selectedAddress?.address_line ?? form.addressLine,
      city: selectedAddress?.city ?? form.city,
      state: selectedAddress?.state ?? form.state,
      postal_code: selectedAddress?.postal_code ?? form.postalCode,
      landmark: (selectedAddress?.landmark ?? form.landmark) || null,
      latitude:
        selectedAddress?.latitude ??
        (form.latitude ? Number(form.latitude) : null),
      longitude:
        selectedAddress?.longitude ??
        (form.longitude ? Number(form.longitude) : null),
      delivery_instructions: form.deliveryInstructions || null,
      payment_method: "cod",
    };

    if (
      !orderPayload.address_line ||
      !orderPayload.city ||
      !orderPayload.postal_code
    ) {
      Alert.alert(
        "Delivery details missing",
        "Choose or add a valid address before placing the order.",
      );
      return;
    }

    try {
      setSaving(true);
      await createOrder(accessToken, orderPayload);
      clearCart();
      router.replace("/orders");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to place the order.";
      Alert.alert("Order failed", message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Checkout</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.summaryBox}>
          <Text style={styles.sectionTitle}>Delivery</Text>
          <Text style={styles.muted}>Items: {items.length}</Text>
          <View style={styles.summaryRow}>
            <Text style={styles.label}>Items total</Text>
            <Text style={styles.value}>{rupees(subtotal)}</Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.label}>Delivery</Text>
            <Text style={styles.value}>{rupees(0)}</Text>
          </View>
          <View style={[styles.summaryRow, styles.totalRow]}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalValue}>{rupees(orderSummary)}</Text>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Saved addresses</Text>
          {loading ? (
            <Text style={styles.muted}>Loading addresses…</Text>
          ) : null}
          {addresses.length === 0 ? (
            <Text style={styles.muted}>
              No saved addresses yet. Add one below.
            </Text>
          ) : (
            addresses.map((address) => (
              <Pressable
                key={address.id}
                style={[
                  styles.addressOption,
                  selectedAddressId === address.id &&
                    styles.addressOptionSelected,
                ]}
                onPress={() => setSelectedAddressId(address.id)}
              >
                <View style={styles.addressRow}>
                  <Text style={styles.addressLabel}>{address.label}</Text>
                  {address.is_default ? (
                    <Text style={styles.badge}>Default</Text>
                  ) : null}
                </View>
                <Text style={styles.addressText}>{address.recipient_name}</Text>
                <Text style={styles.addressText}>{address.address_line}</Text>
                <Text style={styles.addressText}>
                  {address.city}, {address.state}
                </Text>
              </Pressable>
            ))
          )}
        </View>

        <View style={styles.card}>
          <View style={styles.inlineHeader}>
            <Text style={styles.sectionTitle}>Address details</Text>
            <Pressable
              onPress={requestCurrentLocation}
              style={styles.linkButton}
            >
              <Text style={styles.linkText}>Use current location</Text>
            </Pressable>
          </View>

          <TextInput
            placeholder="Address label"
            value={form.label}
            onChangeText={(value) =>
              setForm((current) => ({ ...current, label: value }))
            }
            style={styles.input}
          />
          <TextInput
            placeholder="Recipient name"
            value={form.recipientName}
            onChangeText={(value) =>
              setForm((current) => ({ ...current, recipientName: value }))
            }
            style={styles.input}
          />
          <TextInput
            placeholder="Phone number"
            keyboardType="phone-pad"
            value={form.phone}
            onChangeText={(value) =>
              setForm((current) => ({ ...current, phone: value }))
            }
            style={styles.input}
          />
          <TextInput
            placeholder="House / street"
            value={form.addressLine}
            onChangeText={(value) =>
              setForm((current) => ({ ...current, addressLine: value }))
            }
            style={styles.input}
          />
          <TextInput
            placeholder="Landmark"
            value={form.landmark}
            onChangeText={(value) =>
              setForm((current) => ({ ...current, landmark: value }))
            }
            style={styles.input}
          />
          <View style={styles.splitRow}>
            <TextInput
              placeholder="City"
              value={form.city}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, city: value }))
              }
              style={[styles.input, styles.halfInput]}
            />
            <TextInput
              placeholder="State"
              value={form.state}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, state: value }))
              }
              style={[styles.input, styles.halfInput]}
            />
          </View>
          <View style={styles.splitRow}>
            <TextInput
              placeholder="Postal code"
              value={form.postalCode}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, postalCode: value }))
              }
              style={[styles.input, styles.halfInput]}
            />
            <TextInput
              placeholder="Lat"
              value={form.latitude}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, latitude: value }))
              }
              style={[styles.input, styles.halfInput]}
              keyboardType="numeric"
            />
          </View>
          <TextInput
            placeholder="Longitude"
            value={form.longitude}
            onChangeText={(value) =>
              setForm((current) => ({ ...current, longitude: value }))
            }
            style={styles.input}
            keyboardType="numeric"
          />
          <TextInput
            placeholder="Delivery instructions"
            value={form.deliveryInstructions}
            onChangeText={(value) =>
              setForm((current) => ({
                ...current,
                deliveryInstructions: value,
              }))
            }
            style={styles.input}
          />
          <Pressable
            style={styles.secondaryButton}
            onPress={saveAddress}
            disabled={saving}
          >
            <Text style={styles.secondaryText}>
              {saving ? "Saving…" : "Save address"}
            </Text>
          </Pressable>
        </View>

        <Pressable
          style={styles.primaryButton}
          onPress={placeOrder}
          disabled={saving}
        >
          <Text style={styles.primaryText}>
            {saving ? "Placing order…" : "Place order"}
          </Text>
        </Pressable>
      </ScrollView>
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
  title: { fontSize: 28, fontWeight: "800", color: "#241913" },
  headerSpacer: { width: 40 },
  content: { padding: 20, paddingBottom: 40, gap: 16 },
  summaryBox: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  sectionTitle: {
    color: "#241913",
    fontSize: 18,
    fontWeight: "800",
    marginBottom: 8,
  },
  muted: { color: "#6D625D", marginBottom: 8 },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 8,
  },
  label: { color: "#5F5049" },
  value: { color: "#241913", fontWeight: "700" },
  totalRow: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderColor: "#F0E3DC",
  },
  totalLabel: { color: "#241913", fontWeight: "800" },
  totalValue: { color: "#D83B05", fontWeight: "900" },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  addressOption: {
    borderWidth: 1,
    borderColor: "#EADDD6",
    borderRadius: 12,
    padding: 12,
    marginTop: 10,
  },
  addressOptionSelected: { borderColor: "#FF5A1F", backgroundColor: "#FFF3EE" },
  addressRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  addressLabel: { color: "#241913", fontWeight: "800", fontSize: 15 },
  addressText: { color: "#5F5049", marginTop: 4 },
  badge: {
    backgroundColor: "#FFE4D6",
    color: "#D83B05",
    fontWeight: "800",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    overflow: "hidden",
  },
  inlineHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  linkButton: { paddingHorizontal: 8, paddingVertical: 6 },
  linkText: { color: "#D83B05", fontWeight: "700" },
  input: {
    backgroundColor: "#FFF8F5",
    borderColor: "#EADDD6",
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    marginTop: 10,
    color: "#241913",
  },
  splitRow: { flexDirection: "row", gap: 8 },
  halfInput: { flex: 1 },
  secondaryButton: {
    backgroundColor: "#FFF0E8",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 12,
  },
  secondaryText: { color: "#D83B05", fontWeight: "800" },
  primaryButton: {
    marginTop: 8,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryText: { color: "#fff", fontWeight: "800" },
});
