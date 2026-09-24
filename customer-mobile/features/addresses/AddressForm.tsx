import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    StyleSheet,
    Switch,
    Text,
    TextInput,
    View,
} from "react-native";

import { useLocationPicker } from "@/features/addresses/location-picker-context";
import { usePickedPlace } from "@/features/addresses/place-search-context";
import type { Address, AddressPayload } from "@/services/api/addressesApi";

// Maps & Location System Phase 5/6/9 — Customer Address Management +
// Map Picker + Forward Geocoding/Address Search. Manual text entry
// remains the primary path (never removed). Phase 6 adds an optional
// "Pick location on map" button that fills latitude/longitude
// alongside it; Phase 9 adds "Search for an address," which can fill
// the text fields AND coordinates AND formatted_address/place_id in
// one step — neither ever replaces manual entry, both are just faster
// starting points the customer still reviews before saving.

export type AddressFormValues = {
  label: string;
  recipient_name: string;
  phone: string;
  address_line: string;
  city: string;
  district: string;
  state: string;
  postal_code: string;
  landmark: string;
  latitude: number | null;
  longitude: number | null;
  formatted_address: string | null;
  place_id: string | null;
  is_default: boolean;
};

export function addressToFormValues(address: Address): AddressFormValues {
  return {
    label: address.label,
    recipient_name: address.recipient_name,
    phone: address.phone,
    address_line: address.address_line,
    city: address.city,
    district: address.district ?? "",
    state: address.state,
    postal_code: address.postal_code,
    landmark: address.landmark ?? "",
    latitude: address.latitude,
    longitude: address.longitude,
    formatted_address: address.formatted_address,
    place_id: address.place_id,
    is_default: address.is_default,
  };
}

const EMPTY_VALUES: AddressFormValues = {
  label: "Home",
  recipient_name: "",
  phone: "",
  address_line: "",
  city: "",
  district: "",
  state: "",
  postal_code: "",
  landmark: "",
  latitude: null,
  longitude: null,
  formatted_address: null,
  place_id: null,
  is_default: false,
};

export function validateAddressForm(values: AddressFormValues): string | null {
  if (values.recipient_name.trim().length < 2) return "Enter the recipient's name.";
  if (values.phone.trim().length < 8) return "Enter a valid phone number.";
  if (values.address_line.trim().length < 3) return "Enter the address.";
  if (values.city.trim().length < 2) return "Enter a city.";
  if (values.state.trim().length < 2) return "Enter a state.";
  if (values.postal_code.trim().length < 3) return "Enter a valid postal code.";
  return null;
}

export function formValuesToPayload(values: AddressFormValues): AddressPayload {
  return {
    label: values.label.trim() || "Home",
    recipient_name: values.recipient_name.trim(),
    phone: values.phone.trim(),
    address_line: values.address_line.trim(),
    city: values.city.trim(),
    district: values.district.trim() || null,
    state: values.state.trim(),
    postal_code: values.postal_code.trim(),
    landmark: values.landmark.trim() || null,
    latitude: values.latitude,
    longitude: values.longitude,
    formatted_address: values.formatted_address,
    place_id: values.place_id,
    is_default: values.is_default,
  };
}

export function AddressForm({
  initialValues,
  onSubmit,
  submitLabel,
}: {
  initialValues?: Address;
  onSubmit: (payload: AddressPayload) => Promise<void>;
  submitLabel: string;
}) {
  const router = useRouter();
  const { pickedLocation, setPickedLocation } = useLocationPicker();
  const { pickedPlace, setPickedPlace } = usePickedPlace();
  const [values, setValues] = useState<AddressFormValues>(
    initialValues ? addressToFormValues(initialValues) : EMPTY_VALUES,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function set<K extends keyof AddressFormValues>(key: K, value: AddressFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  // Picks up a coordinate confirmed on the map-picker screen when this
  // form regains focus after navigating back from it — then clears it
  // immediately so it can never leak into a later, unrelated form.
  useFocusEffect(
    useCallback(() => {
      if (pickedLocation) {
        setValues((current) => ({ ...current, latitude: pickedLocation.latitude, longitude: pickedLocation.longitude }));
        setPickedLocation(null);
      }
    }, [pickedLocation, setPickedLocation]),
  );

  // Same pattern, for a place selected on the search screen — fills the
  // text fields a search result actually carries, never recipient_name/
  // phone/label/landmark/is_default, which stay whatever the customer
  // already had (a search result has no opinion on who's receiving the
  // order or what to call this address).
  useFocusEffect(
    useCallback(() => {
      if (pickedPlace) {
        setValues((current) => ({
          ...current,
          address_line: pickedPlace.address_line || current.address_line,
          city: pickedPlace.city || current.city,
          district: pickedPlace.district ?? current.district,
          state: pickedPlace.state || current.state,
          postal_code: pickedPlace.postal_code || current.postal_code,
          latitude: pickedPlace.latitude,
          longitude: pickedPlace.longitude,
          formatted_address: pickedPlace.formatted_address,
          place_id: pickedPlace.place_id,
        }));
        setPickedPlace(null);
      }
    }, [pickedPlace, setPickedPlace]),
  );

  async function handleSubmit() {
    const validationError = validateAddressForm(values);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onSubmit(formValuesToPayload(values));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save address.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <View>
      <Pressable style={styles.searchButton} onPress={() => router.push("/addresses/search")}>
        <Text style={styles.searchButtonText}>🔎 Search for a home, shop, landmark…</Text>
      </Pressable>

      <Field label="Label (e.g. Home, Work)" value={values.label} onChangeText={(v) => set("label", v)} />
      <Field label="Recipient name" value={values.recipient_name} onChangeText={(v) => set("recipient_name", v)} />
      <Field label="Phone" value={values.phone} onChangeText={(v) => set("phone", v)} keyboardType="phone-pad" />
      <Field label="Address" value={values.address_line} onChangeText={(v) => set("address_line", v)} multiline />
      <Field label="Landmark (optional)" value={values.landmark} onChangeText={(v) => set("landmark", v)} />
      <Field label="City" value={values.city} onChangeText={(v) => set("city", v)} />
      <Field label="District (optional)" value={values.district} onChangeText={(v) => set("district", v)} />
      <Field label="State" value={values.state} onChangeText={(v) => set("state", v)} />
      <Field label="Postal code" value={values.postal_code} onChangeText={(v) => set("postal_code", v)} keyboardType="number-pad" />

      <Pressable style={styles.mapButton} onPress={() => router.push("/addresses/map-picker")}>
        <Text style={styles.mapButtonText}>
          {values.latitude != null ? "📍 Location set — change on map" : "📍 Pick location on map"}
        </Text>
      </Pressable>

      <View style={styles.defaultRow}>
        <Text style={styles.defaultLabel}>Set as default address</Text>
        <Switch
          value={values.is_default}
          onValueChange={(v) => set("is_default", v)}
          trackColor={{ false: "#E5D9D1", true: "#FFB088" }}
          thumbColor={values.is_default ? "#FF5A1F" : "#fff"}
        />
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable style={styles.submitButton} onPress={handleSubmit} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.submitLabel}>{submitLabel}</Text>}
      </Pressable>
    </View>
  );
}

function Field({
  label,
  value,
  onChangeText,
  multiline,
  keyboardType,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  multiline?: boolean;
  keyboardType?: "phone-pad" | "number-pad";
}) {
  return (
    <View style={styles.fieldWrap}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        style={[styles.input, multiline && styles.inputMultiline]}
        value={value}
        onChangeText={onChangeText}
        multiline={multiline}
        keyboardType={keyboardType}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fieldWrap: { marginTop: 14 },
  fieldLabel: { color: "#352C27", fontSize: 14, fontWeight: "700" },
  input: {
    height: 48,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#E5D9D1",
    backgroundColor: "#fff",
    paddingHorizontal: 12,
    fontSize: 16,
    color: "#17120F",
    marginTop: 8,
  },
  inputMultiline: { height: 76, paddingTop: 12, textAlignVertical: "top" },
  searchButton: {
    borderWidth: 1,
    borderColor: "#F0E3DC",
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
    backgroundColor: "#fff",
  },
  searchButtonText: { color: "#D83B05", fontWeight: "700", fontSize: 14 },
  mapButton: {
    marginTop: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
    backgroundColor: "#fff",
  },
  mapButtonText: { color: "#D83B05", fontWeight: "700", fontSize: 14 },
  defaultRow: {
    marginTop: 18,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  defaultLabel: { color: "#241913", fontSize: 15, fontWeight: "700" },
  error: {
    color: "#B42318",
    lineHeight: 20,
    backgroundColor: "#FEE4E2",
    borderRadius: 8,
    padding: 10,
    marginTop: 16,
  },
  submitButton: {
    height: 48,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 20,
  },
  submitLabel: { color: "#fff", fontSize: 16, fontWeight: "800" },
});
