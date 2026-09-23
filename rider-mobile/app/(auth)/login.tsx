import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Button,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
} from "react-native";

import { useThemeColors } from "@/hooks/use-theme-colors";
import { useAuthStore } from "@/store/authStore";

export default function RiderLoginScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const signIn = useAuthStore((state) => state.signIn);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin() {
    setLoading(true);
    setError(null);
    try {
      await signIn(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to log in.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={[styles.flex, { backgroundColor: colors.background }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[styles.title, { color: colors.text }]}>Rider login</Text>
        <TextInput
          style={[styles.input, { borderColor: colors.border, color: colors.text }]}
          value={email}
          onChangeText={setEmail}
          placeholder="Email or phone"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          keyboardType="email-address"
          accessibilityLabel="Email or phone"
        />
        <TextInput
          style={[styles.input, { borderColor: colors.border, color: colors.text }]}
          value={password}
          onChangeText={setPassword}
          placeholder="Password"
          placeholderTextColor={colors.muted}
          secureTextEntry
          accessibilityLabel="Password"
        />
        {error ? <Text style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
        <Button
          title={loading ? "Signing in..." : "Login"}
          onPress={handleLogin}
          disabled={loading || !email.trim() || !password}
          accessibilityLabel="Log in"
        />
        <Pressable onPress={() => router.push("/register")} accessibilityRole="link">
          <Text style={[styles.link, { color: colors.primary }]}>New rider? Create an account</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  container: {
    flexGrow: 1,
    justifyContent: "center",
    paddingHorizontal: 24,
    gap: 12,
  },
  title: { fontSize: 28, fontWeight: "700", marginBottom: 8 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  error: {},
  link: { textAlign: "center", marginTop: 8 },
});
