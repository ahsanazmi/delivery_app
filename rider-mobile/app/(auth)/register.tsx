import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
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
import { z } from "zod";

import { useThemeColors } from "@/hooks/use-theme-colors";
import { useAuthStore } from "@/store/authStore";

const registerSchema = z.object({
  name: z.string().min(2, "Enter your full name"),
  email: z.string().email("Enter a valid email address"),
  phone: z
    .string()
    .optional()
    .refine((value) => !value || value.length >= 8, "Enter a valid phone number"),
  password: z.string().min(8, "Password must be at least 8 characters"),
});

type RegisterForm = z.infer<typeof registerSchema>;

export default function RiderRegisterScreen() {
  const router = useRouter();
  const colors = useThemeColors();
  const signUp = useAuthStore((state) => state.signUp);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema),
    defaultValues: { name: "", email: "", phone: "", password: "" },
  });

  async function onSubmit(values: RegisterForm) {
    setSubmitError(null);
    try {
      await signUp({
        name: values.name,
        email: values.email,
        password: values.password,
        phone: values.phone || undefined,
      });
      router.replace("/verification");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unable to create your account.");
    }
  }

  return (
    <KeyboardAvoidingView
      style={[styles.flex, { backgroundColor: colors.background }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={[styles.title, { color: colors.text }]}>Become a delivery partner</Text>

        <Controller
          control={control}
          name="name"
          render={({ field: { value, onChange } }) => (
            <TextInput
              style={[styles.input, { borderColor: colors.border, color: colors.text }]}
              placeholder="Full name"
              placeholderTextColor={colors.muted}
              value={value}
              onChangeText={onChange}
              accessibilityLabel="Full name"
            />
          )}
        />
        {errors.name && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.name.message}</Text>}

        <Controller
          control={control}
          name="email"
          render={({ field: { value, onChange } }) => (
            <TextInput
              style={[styles.input, { borderColor: colors.border, color: colors.text }]}
              placeholder="Email"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              keyboardType="email-address"
              value={value}
              onChangeText={onChange}
              accessibilityLabel="Email"
            />
          )}
        />
        {errors.email && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.email.message}</Text>}

        <Controller
          control={control}
          name="phone"
          render={({ field: { value, onChange } }) => (
            <TextInput
              style={[styles.input, { borderColor: colors.border, color: colors.text }]}
              placeholder="Phone (optional)"
              placeholderTextColor={colors.muted}
              keyboardType="number-pad"
              value={value}
              onChangeText={onChange}
              accessibilityLabel="Phone number, optional"
            />
          )}
        />
        {errors.phone && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.phone.message}</Text>}

        <Controller
          control={control}
          name="password"
          render={({ field: { value, onChange } }) => (
            <TextInput
              style={[styles.input, { borderColor: colors.border, color: colors.text }]}
              placeholder="Password"
              placeholderTextColor={colors.muted}
              secureTextEntry
              value={value}
              onChangeText={onChange}
              accessibilityLabel="Password"
            />
          )}
        />
        {errors.password && <Text style={[styles.fieldError, { color: colors.danger }]}>{errors.password.message}</Text>}

        {submitError ? <Text style={[styles.error, { color: colors.danger }]}>{submitError}</Text> : null}

        <Button
          title={isSubmitting ? "Creating account..." : "Create account"}
          onPress={handleSubmit(onSubmit)}
          disabled={isSubmitting}
          accessibilityLabel="Create account"
        />

        <Pressable onPress={() => router.replace("/login")} accessibilityRole="link">
          <Text style={[styles.link, { color: colors.primary }]}>Already have an account? Log in</Text>
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
    paddingVertical: 32,
    gap: 10,
  },
  title: { fontSize: 26, fontWeight: "700", marginBottom: 8 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  fieldError: { fontSize: 12, marginTop: -6 },
  error: {},
  link: { textAlign: "center", marginTop: 8 },
});
