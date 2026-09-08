import { type ComponentProps, useState } from "react";
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    Pressable,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "@/services/api/apiClient";
import { useSession } from "./session-context";

type Mode = "login" | "register";

type AuthScreenProps = {
  initialMode?: Mode;
};

export function AuthScreen({ initialMode = "login" }: AuthScreenProps) {
  const { signIn, signUp, status } = useSession();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busy = status === "loading";

  async function submit() {
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email or phone number and password.");
      return;
    }
    if (mode === "register" && fullName.trim().length < 2) {
      setError("Enter your full name.");
      return;
    }
    try {
      if (mode === "login") await signIn(email, password);
      else await signUp({ fullName, email, password, phone });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Unable to continue. Please try again.",
      );
    }
  }

  function changeMode() {
    setMode(mode === "login" ? "register" : "login");
    setError(null);
  }

  const registering = mode === "register";
  return (
    <SafeAreaView style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.keyboard}
      >
        <View style={styles.content}>
          <View style={styles.brandMark}>
            <Text style={styles.brandSteam}>~</Text>
            <Text style={styles.brandCup}>☕</Text>
          </View>
          <Text style={styles.title}>
            {registering ? "Start your food journey" : "Welcome back"}
          </Text>
          <Text style={styles.subtitle}>
            {registering
              ? "Create an account to order from local favourites."
              : "Sign in to continue ordering local favourites."}
          </Text>

          <View style={styles.form}>
            {registering && (
              <Field
                label="Full name"
                value={fullName}
                onChangeText={setFullName}
                autoCapitalize="words"
              />
            )}
            {registering && (
              <Field
                label="Phone number (optional)"
                value={phone}
                onChangeText={setPhone}
                keyboardType="phone-pad"
              />
            )}
            <Field
              label={registering ? "Email address" : "Email or phone number"}
              value={email}
              onChangeText={setEmail}
              keyboardType={
                registering || email.includes("@")
                  ? "email-address"
                  : "phone-pad"
              }
              autoCapitalize="none"
            />
            <Field
              label="Password"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
            />
            {error && (
              <Text accessibilityRole="alert" style={styles.error}>
                {error}
              </Text>
            )}
            <Pressable
              accessibilityRole="button"
              disabled={busy}
              onPress={submit}
              style={({ pressed }) => [
                styles.primaryButton,
                (pressed || busy) && styles.buttonPressed,
              ]}
            >
              {busy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.primaryLabel}>
                  {registering ? "Create account" : "Sign in"}
                </Text>
              )}
            </Pressable>
          </View>

          <Pressable
            accessibilityRole="button"
            disabled={busy}
            onPress={changeMode}
            style={styles.modeButton}
          >
            <Text style={styles.modeText}>
              {registering ? "Already have an account? " : "New here? "}
              <Text style={styles.modeLink}>
                {registering ? "Sign in" : "Create account"}
              </Text>
            </Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Field({
  label,
  ...props
}: { label: string } & ComponentProps<typeof TextInput>) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        placeholder={label}
        placeholderTextColor="#9A9A9A"
        style={styles.input}
        {...props}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  keyboard: { flex: 1 },
  content: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 24,
    maxWidth: 480,
    width: "100%",
    alignSelf: "center",
  },
  brandMark: {
    width: 68,
    height: 68,
    borderRadius: 24,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 24,
  },
  brandCup: { fontSize: 28, marginTop: -3 },
  brandSteam: {
    position: "absolute",
    top: -8,
    color: "#fff",
    fontSize: 36,
    fontWeight: "800",
  },
  title: {
    fontSize: 31,
    lineHeight: 38,
    fontWeight: "800",
    color: "#17120F",
    letterSpacing: -0.7,
  },
  subtitle: {
    fontSize: 16,
    lineHeight: 23,
    color: "#6D625D",
    marginTop: 8,
    marginBottom: 32,
  },
  form: { gap: 16 },
  label: { color: "#352C27", fontSize: 14, fontWeight: "700", marginBottom: 7 },
  input: {
    height: 52,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#E5D9D1",
    backgroundColor: "#fff",
    paddingHorizontal: 15,
    fontSize: 16,
    color: "#17120F",
  },
  primaryButton: {
    height: 54,
    borderRadius: 14,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 8,
  },
  buttonPressed: { opacity: 0.72 },
  primaryLabel: { color: "#fff", fontSize: 16, fontWeight: "800" },
  error: {
    color: "#B42318",
    lineHeight: 20,
    backgroundColor: "#FEE4E2",
    borderRadius: 8,
    padding: 10,
  },
  modeButton: { marginTop: 24, alignItems: "center", padding: 8 },
  modeText: { color: "#6D625D", fontSize: 14 },
  modeLink: { color: "#D83B05", fontWeight: "800" },
});
