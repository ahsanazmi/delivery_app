import { useColorScheme } from "react-native";

// A deliberately small palette — riders use this app while working, so the
// whole point of Phase 29 is to reduce visual noise, not add a full design
// system. Every screen pulls from this single source instead of hardcoding
// its own hex values, which is what makes dark mode support here a five-
// minute addition instead of a per-screen rewrite.
export type ThemeColors = {
  background: string;
  card: string;
  border: string;
  text: string;
  muted: string;
  primary: string;
  primaryText: string;
  success: string;
  danger: string;
  warning: string;
  skeleton: string;
};

const light: ThemeColors = {
  background: "#f9fafb",
  card: "#ffffff",
  border: "#d1d5db",
  text: "#111827",
  muted: "#6b7280",
  primary: "#2563eb",
  primaryText: "#ffffff",
  success: "#15803d",
  danger: "#b91c1c",
  warning: "#b45309",
  skeleton: "#e5e7eb",
};

const dark: ThemeColors = {
  background: "#0f172a",
  card: "#1e293b",
  border: "#334155",
  text: "#f1f5f9",
  muted: "#94a3b8",
  primary: "#3b82f6",
  primaryText: "#ffffff",
  success: "#4ade80",
  danger: "#f87171",
  warning: "#fbbf24",
  skeleton: "#334155",
};

export function useThemeColors(): ThemeColors {
  const scheme = useColorScheme();
  return scheme === "dark" ? dark : light;
}
