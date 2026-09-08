import { useRouter } from "expo-router";
import { useState } from "react";
import { Button, StyleSheet, Text, TextInput, View } from "react-native";

import { useSession } from "@/features/auth/session-context";

export default function RestaurantLoginScreen() {
  const router = useRouter();
  const { signIn, signOut, user } = useSession();
  const [email, setEmail] = useState("restaurant@example.com");
  const [password, setPassword] = useState("restaurant123");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin() {
    setLoading(true);
    setError(null);
    try {
      const authenticatedUser = await signIn(email.trim(), password);
      if (authenticatedUser.role !== "RESTAURANT") {
        signOut();
        setError("This account is not authorized for the restaurant portal.");
        return;
      }
      router.replace("/restaurant");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to log in.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Restaurant portal</Text>
      <TextInput
        style={styles.input}
        value={email}
        onChangeText={setEmail}
        placeholder="Restaurant email"
        autoCapitalize="none"
        keyboardType="email-address"
      />
      <TextInput
        style={styles.input}
        value={password}
        onChangeText={setPassword}
        placeholder="Password"
        secureTextEntry
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {user ? (
        <Text style={styles.helper}>Signed in as {user.name}</Text>
      ) : null}
      <Button
        title={loading ? "Signing in..." : "Login"}
        onPress={handleLogin}
        disabled={loading}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 24,
    gap: 12,
  },
  title: {
    fontSize: 28,
    fontWeight: "700",
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  error: { color: "#b91c1c" },
  helper: { color: "#4b5563" },
});
