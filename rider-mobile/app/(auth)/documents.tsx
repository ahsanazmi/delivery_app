import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Button,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { ErrorState } from "@/components/ErrorState";
import {
  createRiderDocument,
  deleteRiderDocument,
  listRiderDocuments,
  updateRiderDocument,
  type DocumentType,
  type RiderDocument,
} from "@/services/api/documentsApi";
import { useAuthStore } from "@/store/authStore";

const DOCUMENT_TYPES: { type: DocumentType; label: string }[] = [
  { type: "DRIVING_LICENSE", label: "Driving License" },
  { type: "VEHICLE_REGISTRATION", label: "Vehicle Registration" },
  { type: "IDENTITY_DOCUMENT", label: "Identity Document" },
  { type: "BANK_DOCUMENT", label: "Bank Document" },
  { type: "PROFILE_PHOTO", label: "Profile Photo" },
];

const STATUS_LABEL: Record<RiderDocument["verification_status"], string> = {
  PENDING: "Pending review",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

export default function RiderDocumentsScreen() {
  const router = useRouter();
  const accessToken = useAuthStore((state) => state.accessToken);
  const [documents, setDocuments] = useState<RiderDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Which document type's form is currently open (upload or replace) —
  // only one at a time, keyed by type since each type has at most one document.
  const [editingType, setEditingType] = useState<DocumentType | null>(null);
  const [urlInput, setUrlInput] = useState("");
  const [numberInput, setNumberInput] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listRiderDocuments(accessToken);
      setDocuments(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load your documents.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  function startEditing(type: DocumentType, existing?: RiderDocument) {
    setEditingType(type);
    setUrlInput(existing?.document_url ?? "");
    setNumberInput(existing?.document_number ?? "");
    setError(null);
  }

  function cancelEditing() {
    setEditingType(null);
    setUrlInput("");
    setNumberInput("");
  }

  async function handleSave(existing?: RiderDocument) {
    if (!accessToken || !editingType || !urlInput.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (existing) {
        const updated = await updateRiderDocument(accessToken, existing.id, {
          document_url: urlInput.trim(),
          document_number: numberInput.trim() || undefined,
        });
        setDocuments((current) => current.map((doc) => (doc.id === updated.id ? updated : doc)));
      } else {
        const created = await createRiderDocument(accessToken, {
          document_type: editingType,
          document_url: urlInput.trim(),
          document_number: numberInput.trim() || undefined,
        });
        setDocuments((current) => [...current, created]);
      }
      cancelEditing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save this document.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(document: RiderDocument) {
    if (!accessToken) return;
    setSaving(true);
    setError(null);
    try {
      await deleteRiderDocument(accessToken, document.id);
      setDocuments((current) => current.filter((doc) => doc.id !== document.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to remove this document.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
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
    <ScrollView
      contentContainerStyle={styles.container}
      keyboardShouldPersistTaps="handled"
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      <View style={styles.headerRow}>
        <Text style={styles.title}>Documents</Text>
        <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back" />
      </View>
      <Text style={styles.subtitle}>
        Upload the documents below so your account can be approved for deliveries.
      </Text>

      {error ? <ErrorState message={error} onRetry={load} /> : null}

      {DOCUMENT_TYPES.map(({ type, label }) => {
        const existing = documents.find((doc) => doc.document_type === type);
        const isEditing = editingType === type;

        return (
          <View key={type} style={styles.card}>
            <View style={styles.cardHeaderRow}>
              <Text style={styles.cardTitle}>{label}</Text>
              {existing && (
                <Text style={[styles.statusPill, styles[`status_${existing.verification_status}` as const]]}>
                  {STATUS_LABEL[existing.verification_status]}
                </Text>
              )}
            </View>

            {existing?.verification_status === "REJECTED" && existing.rejection_reason && (
              <Text style={styles.rejectionReason}>Reason: {existing.rejection_reason}</Text>
            )}

            {isEditing ? (
              <View style={styles.form}>
                <TextInput
                  style={styles.input}
                  value={urlInput}
                  onChangeText={setUrlInput}
                  placeholder="Document URL (https://…)"
                  autoCapitalize="none"
                  accessibilityLabel={`${label} document URL`}
                />
                <TextInput
                  style={styles.input}
                  value={numberInput}
                  onChangeText={setNumberInput}
                  placeholder="Document number (optional)"
                  accessibilityLabel={`${label} document number, optional`}
                />
                <View style={styles.buttonRow}>
                  <Button title="Cancel" onPress={cancelEditing} disabled={saving} />
                  <Button
                    title={saving ? "Saving..." : "Save"}
                    onPress={() => handleSave(existing)}
                    disabled={saving || !urlInput.trim()}
                  />
                </View>
              </View>
            ) : existing ? (
              <View style={styles.buttonRow}>
                <Button title="Replace" onPress={() => startEditing(type, existing)} disabled={saving} />
                <Button title="Remove" onPress={() => handleDelete(existing)} disabled={saving} />
              </View>
            ) : (
              <Button title="Upload" onPress={() => startEditing(type)} disabled={saving} />
            )}
          </View>
        );
      })}
    </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center" },
  container: { padding: 20, gap: 16 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 26, fontWeight: "700" },
  subtitle: { color: "#4b5563" },
  error: { color: "#b91c1c" },
  card: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  cardHeaderRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardTitle: { fontSize: 16, fontWeight: "700" },
  statusPill: {
    fontSize: 12,
    fontWeight: "700",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    overflow: "hidden",
  },
  status_PENDING: { backgroundColor: "#fef3c7", color: "#92400e" },
  status_APPROVED: { backgroundColor: "#dcfce7", color: "#166534" },
  status_REJECTED: { backgroundColor: "#fee2e2", color: "#991b1b" },
  rejectionReason: { color: "#991b1b", fontSize: 13 },
  form: { gap: 8 },
  input: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  buttonRow: { flexDirection: "row", gap: 8, justifyContent: "flex-start" },
});
