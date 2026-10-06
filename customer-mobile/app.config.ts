import type { ExpoConfig } from "expo/config";

const config: ExpoConfig = {
  name: "Say Hi Chai",
  slug: "say-hi-chai-customer",
  version: "1.0.0",
  orientation: "portrait",

  icon: "./assets/images/icon.png",

  scheme: "sayhichaicustomer",

  userInterfaceStyle: "automatic",

  newArchEnabled: true,

  ios: {
    icon: "./assets/expo.icon",

    bundleIdentifier: "com.sayhichai.customer",

    infoPlist: {
      LSApplicationQueriesSchemes: ["tez", "phonepe", "paytmmp"],
    },
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

    "@maplibre/maplibre-react-native",

    [
      "expo-location",
      {
        locationWhenInUsePermission:
          "Say Hi Chai uses your location to help you set your delivery address faster. You can always enter it manually instead.",
      },
    ],
  ],

  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
};

export default config;
