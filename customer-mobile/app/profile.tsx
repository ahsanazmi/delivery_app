import { Redirect, useRouter } from "expo-router";
import {
    ActivityIndicator,
    Pressable,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { updateProfile } from "@/services/api/profileApi";

export default function ProfileScreen() {
  const router = useRouter();
  const { user, accessToken, signOut, refresh } = useSession();
  const [editing, setEditing] = React.useState(false);
  const [name, setName] = React.useState(user?.name ?? "");
  const [email, setEmail] = React.useState(user?.email ?? "");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (!user) return <Redirect href="/login" />;

  async function save() {
    setError(null);
    if (!accessToken) return;
    if (name.trim().length < 2) {
      setError("Name must be at least 2 characters");
      return;
    }
    if (email && !email.includes("@")) {
      setError("Enter a valid email address");
      return;
    }
    setBusy(true);
    try {
      await updateProfile(accessToken, {
        name: name.trim(),
        email: email ? email.trim() : null,
      });
      await refresh();
      setEditing(false);
    } catch (e) {
      setError("Unable to update profile");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.content}>
        <Text style={styles.header}>Profile</Text>

        <View style={styles.card}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>
              {user.name.charAt(0).toUpperCase()}
            </Text>
          </View>
          {!editing ? (
            <>
              <Text style={styles.name}>{user.name}</Text>
              <Text style={styles.role}>{user.role}</Text>
              <Info label="Email" value={user.email ?? "Not added"} />
              <Info label="Phone" value={user.phone ?? "Not added"} />
            </>
          ) : (
            <>
              <Text style={styles.label}>Full name</Text>
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
              />
              <Text style={styles.label}>Email address</Text>
              <TextInput
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
              />
              {error ? <Text style={styles.error}>{error}</Text> : null}
            </>
          )}

          <View style={{ marginTop: 18 }}>
            {!editing ? (
              <Pressable
                onPress={() => setEditing(true)}
                style={styles.primaryButton}
              >
                <Text style={styles.primaryLabel}>Edit profile</Text>
              </Pressable>
            ) : (
              <Pressable
                onPress={save}
                style={styles.primaryButton}
                disabled={busy}
              >
                {busy ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.primaryLabel}>Save</Text>
                )}
              </Pressable>
            )}
          </View>
        </View>

        <Pressable onPress={() => router.push("/payments")} style={styles.menuItem}>
          <Text style={styles.menuItemText}>Payment history</Text>
          <Text style={styles.menuItemChevron}>›</Text>
        </Pressable>

        <Pressable onPress={signOut} style={styles.signOut}>
          <Text style={styles.signOutText}>Sign out</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

import React from "react";

function Info({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.info}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  content: {
    flex: 1,
    padding: 24,
    maxWidth: 520,
    width: "100%",
    alignSelf: "center",
  },
  header: { color: "#241913", fontSize: 29, fontWeight: "800", marginTop: 18 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 20,
    marginTop: 24,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  avatar: {
    height: 66,
    width: 66,
    borderRadius: 33,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FFE4D6",
  },
  avatarText: { color: "#D83B05", fontSize: 25, fontWeight: "900" },
  name: { color: "#241913", fontSize: 21, fontWeight: "800", marginTop: 14 },
  role: {
    color: "#D83B05",
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 0.8,
    marginTop: 4,
  },
  info: {
    marginTop: 20,
    borderTopWidth: 1,
    borderColor: "#F0E3DC",
    paddingTop: 14,
  },
  infoLabel: { color: "#8A7C74", fontSize: 12 },
  infoValue: { color: "#241913", fontWeight: "700", marginTop: 4 },
  label: { color: "#352C27", fontSize: 14, fontWeight: "700", marginTop: 12 },
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
  error: {
    color: "#B42318",
    lineHeight: 20,
    backgroundColor: "#FEE4E2",
    borderRadius: 8,
    padding: 10,
    marginTop: 10,
  },
  primaryButton: {
    height: 48,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
  },
  primaryLabel: { color: "#fff", fontSize: 16, fontWeight: "800" },
  menuItem: {
    marginTop: 24,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#fff",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    paddingHorizontal: 16,
    paddingVertical: 16,
  },
  menuItemText: { color: "#241913", fontWeight: "700", fontSize: 15 },
  menuItemChevron: { color: "#8A7C74", fontSize: 20, fontWeight: "700" },
  signOut: {
    marginTop: 18,
    padding: 14,
    borderRadius: 12,
    backgroundColor: "#FEE4E2",
    alignItems: "center",
  },
  signOutText: { color: "#B42318", fontWeight: "800" },
});
