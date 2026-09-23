import { zodResolver } from "@hookform/resolvers/zod";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import {
  ActivityIndicator,
  Alert,
  Button,
  Image,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { z } from "zod";

import { useThemeColors } from "@/hooks/use-theme-colors";
import { getRiderProfile, updateRiderProfile } from "@/services/api/riderApi";
import { useAuthStore } from "@/store/authStore";

const profileSchema = z.object({
  name: z.string().min(2, "Enter your full name"),
  email: z.string().email("Enter a valid email address").optional().or(z.literal("")),
  phone: z
    .string()
    .optional()
    .refine((value) => !value || value.length >= 8, "Enter a valid phone number"),
  profile_image: z.string().optional().or(z.literal("")),
});

type ProfileForm = z.infer<typeof profileSchema>;

export default function RiderProfileScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const user = useAuthStore((state) => state.user);
  const accessToken = useAuthStore((state) => state.accessToken);
  const setUser = useAuthStore((state) => state.setUser);
  const signOut = useAuthStore((state) => state.signOut);

  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(true);

  useFocusEffect(
    useCallback(() => {
      if (!accessToken) return;
      let cancelled = false;
      void getRiderProfile(accessToken)
        .then((profile) => {
          if (!cancelled) setUser(profile);
        })
        .catch(() => {
          // Fall back silently to whatever's already in the store — the
          // screen still shows the last-known profile instead of an error.
        })
        .finally(() => {
          if (!cancelled) setLoadingProfile(false);
        });
      return () => {
        cancelled = true;
      };
    }, [accessToken, setUser]),
  );

  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      name: user?.name ?? "",
      email: user?.email ?? "",
      phone: user?.phone ?? "",
      profile_image: user?.profile_image ?? "",
    },
  });

  function startEditing() {
    reset({
      name: user?.name ?? "",
      email: user?.email ?? "",
      phone: user?.phone ?? "",
      profile_image: user?.profile_image ?? "",
    });
    setError(null);
    setSuccessMessage(null);
    setEditing(true);
  }

  async function onSubmit(values: ProfileForm) {
    if (!accessToken) return;
    setError(null);
    try {
      const updated = await updateRiderProfile(accessToken, {
        name: values.name,
        email: values.email || undefined,
        phone: values.phone || undefined,
        profile_image: values.profile_image || undefined,
      });
      setUser(updated);
      setEditing(false);
      setSuccessMessage("Profile updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update your profile.");
    }
  }

  function confirmLogout() {
    // A rider mid-shift accidentally tapping this would lose their session
    // context — worth one confirmation, unlike most navigation here.
    Alert.alert("Log out?", "You'll need to sign in again to go back online.", [
      { text: "Cancel", style: "cancel" },
      { text: "Log out", style: "destructive", onPress: () => void handleLogout() },
    ]);
  }

  async function handleLogout() {
    await signOut();
    router.replace("/login");
  }

  if (!user || loadingProfile) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? 64 : 0}
    >
      <ScrollView
        contentContainerStyle={[styles.container, { backgroundColor: colors.background }]}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.headerRow}>
          <Text style={[styles.title, { color: colors.text }]}>Profile</Text>
          <Button title="Back" onPress={() => router.back()} accessibilityLabel="Back to dashboard" />
        </View>

        <View style={styles.avatarWrap}>
          {user.profile_image ? (
            <Image source={{ uri: user.profile_image }} style={styles.avatar} accessibilityLabel="Your profile photo" />
          ) : (
            <View style={[styles.avatar, styles.avatarPlaceholder, { backgroundColor: colors.skeleton }]}>
              <Text style={[styles.avatarInitial, { color: colors.muted }]}>{user.name.charAt(0).toUpperCase()}</Text>
            </View>
          )}
        </View>

        {successMessage && !editing && <Text style={[styles.success, { color: colors.success }]}>{successMessage}</Text>}

        {editing ? (
          <View style={styles.form}>
            <Text style={[styles.label, { color: colors.text }]}>Full name</Text>
            <Controller
              control={control}
              name="name"
              render={({ field: { value, onChange } }) => (
                <TextInput
                  style={[styles.input, { borderColor: colors.border, color: colors.text }]}
                  value={value}
                  onChangeText={onChange}
                  placeholder="Full name"
                  placeholderTextColor={colors.muted}
                  accessibilityLabel="Full name"
                />
              )}
            />
            {errors.name && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.name.message}</Text>}

            <Text style={[styles.label, { color: colors.text }]}>Email</Text>
            <Controller
              control={control}
              name="email"
              render={({ field: { value, onChange } }) => (
                <TextInput
                  style={[styles.input, { borderColor: colors.border, color: colors.text }]}
                  value={value}
                  onChangeText={onChange}
                  placeholder="Email"
                  placeholderTextColor={colors.muted}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  accessibilityLabel="Email address"
                />
              )}
            />
            {errors.email && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.email.message}</Text>}

            <Text style={[styles.label, { color: colors.text }]}>Phone</Text>
            <Controller
              control={control}
              name="phone"
              render={({ field: { value, onChange } }) => (
                <TextInput
                  style={[styles.input, { borderColor: colors.border, color: colors.text }]}
                  value={value}
                  onChangeText={onChange}
                  placeholder="Phone"
                  placeholderTextColor={colors.muted}
                  keyboardType="number-pad"
                  accessibilityLabel="Phone number"
                />
              )}
            />
            {errors.phone && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.phone.message}</Text>}

            <Text style={[styles.label, { color: colors.text }]}>Profile photo URL</Text>
            <Controller
              control={control}
              name="profile_image"
              render={({ field: { value, onChange } }) => (
                <TextInput
                  style={[styles.input, { borderColor: colors.border, color: colors.text }]}
                  value={value}
                  onChangeText={onChange}
                  placeholder="https://…"
                  placeholderTextColor={colors.muted}
                  autoCapitalize="none"
                  accessibilityLabel="Profile photo URL"
                />
              )}
            />

            {error ? <Text style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}

            <View style={styles.buttonRow}>
              <Button title="Cancel" onPress={() => setEditing(false)} disabled={isSubmitting} />
              <Button
                title={isSubmitting ? "Saving..." : "Save changes"}
                onPress={handleSubmit(onSubmit)}
                disabled={isSubmitting}
              />
            </View>
          </View>
        ) : (
          <View style={[styles.infoCard, { borderColor: colors.border, backgroundColor: colors.card }]}>
            <View style={styles.infoRow}>
              <Text style={[styles.infoLabel, { color: colors.muted }]}>Name</Text>
              <Text style={[styles.infoValue, { color: colors.text }]}>{user.name}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={[styles.infoLabel, { color: colors.muted }]}>Email</Text>
              <Text style={[styles.infoValue, { color: colors.text }]}>{user.email ?? "—"}</Text>
            </View>
            <View style={styles.infoRow}>
              <Text style={[styles.infoLabel, { color: colors.muted }]}>Phone</Text>
              <Text style={[styles.infoValue, { color: colors.text }]}>{user.phone ?? "—"}</Text>
            </View>
            <Button title="Edit profile" onPress={startEditing} accessibilityLabel="Edit profile" />
          </View>
        )}

        <View style={styles.menu}>
          <Button title="Documents" onPress={() => router.push("/documents")} />
          <Button title="Vehicle information" onPress={() => router.push("/vehicle")} />
          <Button title="Wallet" onPress={() => router.push("/wallet")} />
          <Button title="Earnings" onPress={() => router.push("/earnings")} />
          <Button title="Delivery History" onPress={() => router.push("/history")} />
        </View>

        <View style={styles.logoutWrap}>
          <Button title="Logout" onPress={confirmLogout} color={colors.danger} accessibilityLabel="Log out" />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center" },
  container: { padding: 24, gap: 16 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 28, fontWeight: "700" },
  avatarWrap: { alignItems: "center" },
  avatar: { width: 88, height: 88, borderRadius: 44 },
  avatarPlaceholder: { justifyContent: "center", alignItems: "center" },
  avatarInitial: { fontSize: 32, fontWeight: "700" },
  infoCard: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  infoRow: { gap: 2 },
  infoLabel: { fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  infoValue: { fontSize: 16 },
  form: { gap: 6 },
  label: { fontSize: 13, fontWeight: "700", marginTop: 8 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  fieldError: { fontSize: 12 },
  error: { marginTop: 8 },
  success: {},
  buttonRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 12 },
  menu: { gap: 10 },
  logoutWrap: { marginTop: 8 },
});
