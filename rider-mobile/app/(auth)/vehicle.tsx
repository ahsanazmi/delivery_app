import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Button,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { ErrorState } from "@/components/ErrorState";
import { getRiderVehicle, updateRiderVehicle, type VehicleType } from "@/services/api/vehicleApi";
import { useAuthStore } from "@/store/authStore";

const VEHICLE_TYPES: { type: VehicleType; label: string }[] = [
  { type: "BIKE", label: "Bike" },
  { type: "SCOOTER", label: "Scooter" },
  { type: "BICYCLE", label: "Bicycle" },
  { type: "OTHER", label: "Other" },
];

export default function RiderVehicleScreen() {
  const router = useRouter();
  const accessToken = useAuthStore((state) => state.accessToken);

  const [vehicleType, setVehicleType] = useState<VehicleType | null>(null);
  const [vehicleNumber, setVehicleNumber] = useState("");
  const [vehicleModel, setVehicleModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const vehicle = await getRiderVehicle(accessToken);
      setVehicleType(vehicle.vehicle_type);
      setVehicleNumber(vehicle.vehicle_number ?? "");
      setVehicleModel(vehicle.vehicle_model ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load your vehicle information.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function handleSave() {
    if (!accessToken || !vehicleType) {
      setError("Select a vehicle type before saving.");
      return;
    }
    setSaving(true);
    setError(null);
    setSuccessMessage(null);
    try {
      await updateRiderVehicle(accessToken, {
        vehicle_type: vehicleType,
        vehicle_number: vehicleNumber.trim() || undefined,
        vehicle_model: vehicleModel.trim() || undefined,
      });
      setSuccessMessage("Vehicle information updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update your vehicle information.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <View style={styles.headerRow}>
          <Text style={styles.title}>Vehicle information</Text>
          <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back" />
        </View>

        {successMessage ? <Text style={styles.success}>{successMessage}</Text> : null}
        {error ? <ErrorState message={error} onRetry={load} /> : null}

        <Text style={styles.label}>Vehicle type</Text>
        <View style={styles.typeRow}>
          {VEHICLE_TYPES.map(({ type, label }) => {
            const selected = vehicleType === type;
            return (
              <Pressable
                key={type}
                onPress={() => setVehicleType(type)}
                style={[styles.typeChip, selected && styles.typeChipSelected]}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`Vehicle type: ${label}`}
              >
                <Text style={[styles.typeChipLabel, selected && styles.typeChipLabelSelected]}>{label}</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={styles.label}>Vehicle number</Text>
        <TextInput
          style={styles.input}
          value={vehicleNumber}
          onChangeText={setVehicleNumber}
          placeholder="e.g. KA01AB1234"
          autoCapitalize="characters"
          accessibilityLabel="Vehicle number"
        />

        <Text style={styles.label}>Vehicle model</Text>
        <TextInput
          style={styles.input}
          value={vehicleModel}
          onChangeText={setVehicleModel}
          placeholder="e.g. Honda Activa"
          accessibilityLabel="Vehicle model"
        />

        <Button
          title={saving ? "Saving..." : "Update information"}
          onPress={handleSave}
          disabled={saving}
          accessibilityLabel="Update vehicle information"
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center" },
  container: { padding: 20, gap: 12 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 26, fontWeight: "700" },
  success: { color: "#15803d" },
  error: { color: "#b91c1c" },
  label: { fontSize: 13, fontWeight: "700", color: "#374151", marginTop: 8 },
  typeRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  typeChip: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  typeChipSelected: { backgroundColor: "#2563eb", borderColor: "#2563eb" },
  typeChipLabel: { color: "#374151", fontWeight: "600" },
  typeChipLabelSelected: { color: "#fff" },
  input: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
});
