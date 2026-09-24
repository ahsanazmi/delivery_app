import { DarkTheme, DefaultTheme, ThemeProvider } from "@react-navigation/native";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useColorScheme } from "react-native";

import { AnimatedSplashOverlay } from "@/components/animated-icon";
import { LocationPickerProvider } from "@/features/addresses/location-picker-context";
import { PickedPlaceProvider } from "@/features/addresses/place-search-context";
import { SessionProvider } from "@/features/auth/session-context";
import { CartProvider } from "@/features/cart/cart-context";
import { NotificationProvider } from "@/features/notifications/notification-provider";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const colorScheme = useColorScheme();
  return (
    <ThemeProvider value={colorScheme === "dark" ? DarkTheme : DefaultTheme}>
      <SessionProvider>
        <NotificationProvider>
          <CartProvider>
            <LocationPickerProvider>
              <PickedPlaceProvider>
                <AnimatedSplashOverlay />
                <Stack screenOptions={{ headerShown: false }}>
                  <Stack.Screen name="index" />
                  <Stack.Screen name="splash" />
                  <Stack.Screen name="login" />
                  <Stack.Screen name="home" />
                  <Stack.Screen name="search" />
                  <Stack.Screen name="cart" />
                  <Stack.Screen name="checkout" />
                  <Stack.Screen name="orders" />
                  <Stack.Screen name="orders/[id]" />
                  <Stack.Screen name="payments" />
                  <Stack.Screen name="addresses" />
                  <Stack.Screen name="addresses/new" />
                  <Stack.Screen name="addresses/[id]" />
                  <Stack.Screen name="addresses/map-picker" />
                  <Stack.Screen name="addresses/search" />
                  <Stack.Screen name="track/[id]" />
                  <Stack.Screen name="favorites" />
                  <Stack.Screen name="notifications" />
                  <Stack.Screen name="restaurants/index" />
                  <Stack.Screen name="restaurants/[id]" />
                  <Stack.Screen name="category/[id]" />
                  <Stack.Screen name="profile" />
                </Stack>
              </PickedPlaceProvider>
            </LocationPickerProvider>
          </CartProvider>
        </NotificationProvider>
      </SessionProvider>
    </ThemeProvider>
  );
}
