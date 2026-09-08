Android Development guide for Say Hi Chai (FastAPI backend + React Native frontend)

Overview

- Backend: FastAPI in `backend/` (run on port 8000 by default)
- Frontend: Expo-managed React Native in project root
- Goal: Run and develop Android frontend connected to local FastAPI backend

1. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

2. Android emulator vs physical device

- Emulator (Android Studio / AVD): Use `http://10.0.2.2:8000` to reach host machine from the emulator.
- Genymotion: Use `http://10.0.3.2:8000`.
- Physical device: Use your machine IP on the local network (e.g., `http://192.168.1.12:8000`) and ensure firewall allows access.

3. Configure frontend to hit backend

- `src/services/api/apiClient.ts` defaults to `http://10.0.2.2:8000` for Android emulator. Edit `API_BASE` or set environment variables if you need a different host.

4. Start Expo (quick development with Expo Go)

```bash
# from project root
npm install
npx expo start
```

- Open the project in Expo Go on your device (scan QR) or on emulator.
- If Expo Go shows "requires newer version", either update Expo Go on device/play store or use a dev client (see below).

5. Run on an Android emulator (native build)

- Quick (requires native toolchain & prebuild):

```bash
npx expo prebuild    # generates android/ and ios/ if you need native
npx expo run:android # builds and installs on connected emulator/device
```

- This performs a native build and installs the app on the emulator. Use this when you need native modules or full debug.

6. Create a custom dev client with EAS (recommended when Expo Go isn't compatible)

```bash
npm install -g eas-cli
eas login             # authenticate with your Expo account
# create an Android development build (one-time or as needed)
eas build --profile development -p android
# or use 'eas build -p android --profile development --local' for local builds (advanced)
```

- After the build finishes, install the generated APK on the device/emulator:

```bash
adb install -r ./path/to/your-dev-client.apk
```

- Start Metro, open the dev client and the project will connect to the local Metro server.

7. Troubleshooting

- Metro cache issues: `npx expo start -c`
- Emulator cannot reach backend: verify backend is running and reachable from host; use `curl http://10.0.2.2:8000/api/v1/restaurants` from the host to validate; confirm emulator networking.
- SDK mismatch with Expo Go: build a dev client (EAS) or downgrade the project's Expo SDK.

8. Useful commands summary

```bash
# backend
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# frontend (Expo)
npm install
npx expo start

# native run (prebuild)
npx expo prebuild
npx expo run:android

# build custom dev client (EAS)
eas build --profile development -p android
adb install -r <apk>
```

If you want, I can:

- Add an npm script that starts backend + expo in parallel for convenience.
- Preconfigure `src/services/api/apiClient.ts` to read from a `.env`.
- Scaffold `android/` with `npx expo prebuild` and commit the native config (I can run prebuild here if you want me to modify the repo).
