import type { ExpoConfig } from "expo/config";

// Maps & Location System Phase 6 — converted from the previous static
// app.json specifically so the Google Maps API key never has to be
// committed to it. A plain app.json is static JSON with no way to read
// an environment variable; app.config.ts runs as real code at
// prebuild/build time, so the key is injected from GOOGLE_MAPS_ANDROID_API_KEY
// (set locally in a gitignored .env, or as an EAS secret for real builds)
// and simply omitted from the built config when that variable is unset —
// matching this project's own established pattern for every other
// provider credential (Razorpay, the backend's own env vars): blank by
// default, never a committed placeholder that looks real.
const googleMapsAndroidApiKey = process.env.GOOGLE_MAPS_ANDROID_API_KEY;

const config: ExpoConfig = {
  name: "Say Hi Chai",
  slug: "say-hi-chai-customer",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/images/icon.png",
  scheme: "sayhichaicustomer",
  userInterfaceStyle: "automatic",
  newArchEnabled: false,
  ios: {
    icon: "./assets/expo.icon",
    bundleIdentifier: "com.sayhichai.customer",
    infoPlist: {
      LSApplicationQueriesSchemes: ["tez", "phonepe", "paytmmp"],
    },
    // iOS falls back to Apple Maps (no key required) when this is unset —
    // only set it if a real key is present, so react-native-maps' iOS
    // Google provider is only requested once one actually exists.
    ...(googleMapsAndroidApiKey ? { config: { googleMapsApiKey: googleMapsAndroidApiKey } } : {}),
  },
  android: {
    package: "com.sayhichai.customer",
    adaptiveIcon: {
      backgroundColor: "#E6F4FE",
      foregroundImage: "./assets/images/android-icon-foreground.png",
      backgroundImage: "./assets/images/android-icon-background.png",
      monochromeImage: "./assets/images/android-icon-monochrome.png",
    },
    predictiveBackGestureEnabled: false,
    // Android's Google Maps SDK has no "use the platform default" fallback
    // the way iOS does — without a real key here, the map view renders
    // blank grey tiles on a real device/emulator. Omitted entirely (not
    // an empty string) when unset, since an empty-string key is its own
    // source of confusing native-side errors.
    ...(googleMapsAndroidApiKey ? { config: { googleMaps: { apiKey: googleMapsAndroidApiKey } } } : {}),
  },
  web: {
    output: "static",
    favicon: "./assets/images/favicon.png",
  },
  plugins: [
    "expo-router",
    [
      "expo-splash-screen",
      {
        backgroundColor: "#208AEF",
        image: "./assets/images/splash-icon.png",
        imageWidth: 76,
      },
    ],
    [
      "expo-notifications",
      {
        icon: "./assets/images/icon.png",
        color: "#FF5A1F",
      },
    ],
    // Live Rider Location Tracking — MapLibre Native, deliberately chosen
    // over react-native-maps for the tracking screen's map (see
    // docs/... rationale: react-native-maps has no Android renderer that
    // isn't backed by Google Play Services, even without an API key).
    // Default options are exactly what's wanted here: `locationEngine:
    // "default"` (not "google") keeps this genuinely Google-Play-
    // Services-free on Android.
    "@maplibre/maplibre-react-native",
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
};

export default config;
