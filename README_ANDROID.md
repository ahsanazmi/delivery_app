When to use the Android platform folder

This project is Expo-managed. Use `src/platform/android` for Android-specific JS/TS code only.

If you need native Android code (Java/Kotlin) or to modify `AndroidManifest.xml`, follow one of these:

- Use `expo prebuild` to generate the `android/` and `ios/` native projects, then edit `android/app/src/main/AndroidManifest.xml`.
- Or use EAS to build a custom dev client or a production build.

Quick commands

```bash
# Prebuild native projects (makes android/ and ios/ folders)
npx expo prebuild

# Run Android (requires Android SDK & emulator)
npx expo run:android
```

Tips

- Keep most code platform-agnostic; only place exceptions in `src/platform/android`.
- Document any manifest or gradle changes in `src/platform/android/manifests` to make future prebuild merges easier.
