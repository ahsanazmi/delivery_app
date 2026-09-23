import { useEffect, useRef } from "react";
import { Animated, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from "react-native";

export function Skeleton({ style }: { style?: StyleProp<ViewStyle> }) {
  const opacity = useRef(new Animated.Value(0.4)).current;

  useEffect(() => {
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 650, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 650, useNativeDriver: true }),
      ]),
    );
    pulse.start();
    return () => pulse.stop();
  }, [opacity]);

  return <Animated.View style={[styles.skeleton, style, { opacity }]} />;
}

export function SectionHeader({
  title,
  actionLabel,
  onAction,
}: {
  title: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {actionLabel && onAction && (
        <Pressable onPress={onAction} hitSlop={8}>
          <Text style={styles.sectionLink}>{actionLabel}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function EmptyState({
  emoji = "🍽️",
  title,
  message,
  actionLabel,
  onAction,
  compact = false,
}: {
  emoji?: string;
  title: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
}) {
  return (
    <View style={[styles.emptyState, compact && styles.emptyStateCompact]}>
      <Text style={compact ? styles.emptyEmojiCompact : styles.emptyEmoji}>{emoji}</Text>
      <Text style={styles.emptyTitle}>{title}</Text>
      {message && <Text style={styles.emptyMessage}>{message}</Text>}
      {actionLabel && onAction && (
        <Pressable style={styles.emptyAction} onPress={onAction}>
          <Text style={styles.emptyActionText}>{actionLabel}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <View style={styles.errorState}>
      <Text style={styles.errorText}>{message}</Text>
      <Pressable style={styles.retryButton} onPress={onRetry}>
        <Text style={styles.retryText}>Try again</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  skeleton: {
    backgroundColor: "#EDE1D9",
    borderRadius: 12,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 10,
    marginBottom: 14,
  },
  sectionTitle: { color: "#241913", fontSize: 20, fontWeight: "800" },
  sectionLink: { color: "#D83B05", fontWeight: "700", fontSize: 13 },
  emptyState: {
    backgroundColor: "#fff",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    padding: 28,
    alignItems: "center",
  },
  emptyStateCompact: { padding: 18 },
  emptyEmoji: { fontSize: 40 },
  emptyEmojiCompact: { fontSize: 26 },
  emptyTitle: {
    color: "#241913",
    fontWeight: "800",
    fontSize: 15,
    marginTop: 10,
    textAlign: "center",
  },
  emptyMessage: {
    color: "#81716A",
    fontSize: 13,
    marginTop: 6,
    textAlign: "center",
    lineHeight: 19,
  },
  emptyAction: {
    marginTop: 14,
    backgroundColor: "#FFF0E8",
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  emptyActionText: { color: "#D83B05", fontWeight: "800", fontSize: 13 },
  errorState: {
    backgroundColor: "#fff",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    padding: 24,
    alignItems: "center",
  },
  errorText: { color: "#B42318", textAlign: "center", lineHeight: 21 },
  retryButton: {
    marginTop: 14,
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 18,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
});
