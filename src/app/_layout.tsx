import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useColorScheme } from "react-native";

import { AnimatedSplashOverlay } from "@/components/animated-icon";
import { SessionProvider } from "@/features/auth/session-context";
import { CartProvider } from "@/features/cart/cart-context";

SplashScreen.preventAutoHideAsync();

export default function TabLayout() {
  const colorScheme = useColorScheme();
  return (
    <ThemeProvider value={colorScheme === "dark" ? DarkTheme : DefaultTheme}>
      <SessionProvider>
        <CartProvider>
          <AnimatedSplashOverlay />
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="index" />
            <Stack.Screen name="splash" />
            <Stack.Screen name="portal" />
            <Stack.Screen name="login" />
            <Stack.Screen name="home" />
            <Stack.Screen name="cart" />
            <Stack.Screen name="checkout" />
            <Stack.Screen name="orders" />
            <Stack.Screen name="orders/[id]" />
            <Stack.Screen name="restaurants/index" />
            <Stack.Screen name="restaurants/[id]" />
            <Stack.Screen name="profile" />
            <Stack.Screen name="admin/login" />
            <Stack.Screen name="admin/dashboard" />
            <Stack.Screen name="rider/login" />
            <Stack.Screen name="rider/index" />
            <Stack.Screen name="rider/[id]" />
            <Stack.Screen name="restaurant/login" />
            <Stack.Screen name="restaurant/index" />
          </Stack>
        </CartProvider>
      </SessionProvider>
    </ThemeProvider>
  );
}
