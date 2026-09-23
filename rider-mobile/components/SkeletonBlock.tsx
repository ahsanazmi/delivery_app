import { useEffect, useRef } from "react";
import { Animated, StyleSheet, View, type DimensionValue } from "react-native";

import { useThemeColors } from "@/hooks/use-theme-colors";

/** A single pulsing placeholder rectangle — the building block for
 * skeleton loading states. No extra dependency: just RN's own Animated API
 * looping opacity between 0.4 and 1. */
export function SkeletonBlock({
  width = "100%",
  height = 16,
  borderRadius = 6,
  style,
}: {
  width?: DimensionValue;
  height?: number;
  borderRadius?: number;
  style?: object;
}) {
  const colors = useThemeColors();
  const opacity = useRef(new Animated.Value(0.4)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[
        { width, height, borderRadius, backgroundColor: colors.skeleton, opacity },
        style,
      ]}
    />
  );
}

/** A pre-built skeleton for a single card in a list (dashboard delivery
 * cards, history rows, etc.) — three lines of decreasing width plus a
 * title-height block, matching the shape of the real cards it stands in for. */
export function SkeletonCard() {
  const colors = useThemeColors();
  return (
    <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
      <SkeletonBlock width="60%" height={18} />
      <SkeletonBlock width="90%" />
      <SkeletonBlock width="40%" />
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 16, gap: 8 },
});
