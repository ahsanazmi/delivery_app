import { StyleSheet, Text, View } from "react-native";

import { useThemeColors } from "@/hooks/use-theme-colors";

export function EmptyState({ icon = "📭", message }: { icon?: string; message: string }) {
  const colors = useThemeColors();
  return (
    <View style={styles.container} accessibilityRole="text">
      <Text style={styles.icon}>{icon}</Text>
      <Text style={[styles.message, { color: colors.muted }]}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignItems: "center", paddingVertical: 24, gap: 6 },
  icon: { fontSize: 28 },
  message: { fontSize: 14, textAlign: "center" },
});
