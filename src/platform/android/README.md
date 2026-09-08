Android platform folder

Purpose

- Place Android-specific React Native code that should only be used when running on Android.
- Useful for platform-conditional components, wrappers around native modules, Android-only permissions handling, or manifest snippets you want to keep tracked in source.

Structure

- components/: Android-specific UI components (e.g., map markers, system UI wrappers)
- screens/: screens that differ significantly on Android
- services/: Android-specific services (e.g., background geolocation helpers)
- native-modules/: bridge code or helpers for native modules (placeholder)
- permissions/: permission request helpers and constants
- manifests/: snippets or recommended AndroidManifest changes (for when you eject)
- styles/: Android-only styling tokens
- assets/: platform-specific images / icons

Usage notes

- In JS/TS, import conditionally:
  - `import { Platform } from 'react-native'`
  - `if (Platform.OS === 'android') { const AndroidOnly = require('./platform/android/components/MyAndroid') }`
- For Expo-managed apps: these files are purely JS/TS helpers. To add native Android code (Java/Kotlin), you'll need to prebuild or eject and use the `android/` native folder.
- Keep platform-agnostic code in `src/components` / `src/screens`. Use `src/platform/android` only when necessary.
