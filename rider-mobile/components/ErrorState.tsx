import { Button, StyleSheet, Text, View } from "react-native";

import { useThemeColors } from "@/hooks/use-theme-colors";

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const colors = useThemeColors();
  return (
    <View style={styles.container} accessibilityRole="alert">
      <Text style={styles.icon}>⚠️</Text>
      <Text style={[styles.message, { color: colors.danger }]}>{message}</Text>
      {onRetry && <Button title="Retry" onPress={onRetry} accessibilityLabel="Retry loading" />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignItems: "center", paddingVertical: 20, gap: 8 },
  icon: { fontSize: 24 },
  message: { fontSize: 14, textAlign: "center" },
});
