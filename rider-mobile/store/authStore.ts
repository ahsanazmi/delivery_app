import * as SecureStore from "expo-secure-store";
import { create } from "zustand";

import { unregisterCurrentDevice } from "@/features/notifications/push-notifications";
import {
  type AuthUser,
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
  refreshAccessToken as apiRefresh,
  register as apiRegister,
  type TokenPair,
} from "@/services/api/authApi";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type RegisterInput = {
  name: string;
  email: string;
  password: string;
  phone?: string;
};

type AuthState = {
  user: AuthUser | null;
  accessToken: string | null;
  refreshToken: string | null;
  status: AuthStatus;
  error: string | null;
  hydrate: () => Promise<void>;
  signIn: (identifier: string, password: string) => Promise<AuthUser>;
  signUp: (input: RegisterInput) => Promise<AuthUser>;
  signOut: () => Promise<void>;
  refreshSession: () => Promise<void>;
  setUser: (user: AuthUser) => void;
};

const ACCESS_TOKEN_KEY = "say-hi-chai-rider-access-token";
const REFRESH_TOKEN_KEY = "say-hi-chai-rider-refresh-token";

async function persistTokens(tokens: TokenPair) {
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, tokens.access_token);
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, tokens.refresh_token);
}

async function clearStoredTokens() {
  await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
  await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
}

async function readStoredTokens(): Promise<TokenPair | null> {
  const [accessToken, refreshToken] = await Promise.all([
    SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
    SecureStore.getItemAsync(REFRESH_TOKEN_KEY),
  ]);
  if (!accessToken || !refreshToken) return null;
  return { access_token: accessToken, refresh_token: refreshToken, token_type: "bearer" };
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  refreshToken: null,
  status: "loading",
  error: null,

  // Called once at app start: tries the stored access token first, falls
  // back to a refresh if it's expired, and only lands on "unauthenticated"
  // if neither works — this is what makes closing and reopening the app not
  // require logging in again.
  async hydrate() {
    const stored = await readStoredTokens();
    if (!stored) {
      set({ status: "unauthenticated" });
      return;
    }

    try {
      const user = await getCurrentUser(stored.access_token);
      set({ user, accessToken: stored.access_token, refreshToken: stored.refresh_token, status: "authenticated" });
    } catch {
      try {
        const refreshed = await apiRefresh(stored.refresh_token);
        await persistTokens(refreshed);
        const user = await getCurrentUser(refreshed.access_token);
        set({
          user,
          accessToken: refreshed.access_token,
          refreshToken: refreshed.refresh_token,
          status: "authenticated",
        });
      } catch {
        await clearStoredTokens();
        set({ user: null, accessToken: null, refreshToken: null, status: "unauthenticated" });
      }
    }
  },

  async signIn(identifier, password) {
    set({ error: null });
    try {
      const tokens = await apiLogin(identifier.trim(), password);
      const user = await getCurrentUser(tokens.access_token);
      if (user.role !== "RIDER") {
        // A real account, just not a rider one (e.g. a customer typed their
        // own email in by mistake) — reject client-side for a clear message,
        // but this is a UX nicety only: every backend rider endpoint checks
        // the role itself regardless of what this app does.
        throw new Error("This account is not registered as a delivery partner.");
      }
      await persistTokens(tokens);
      set({ user, accessToken: tokens.access_token, refreshToken: tokens.refresh_token, status: "authenticated" });
      return user;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to log in.";
      set({ error: message });
      throw error;
    }
  },

  async signUp({ name, email, password, phone }) {
    set({ error: null });
    try {
      await apiRegister({ name: name.trim(), email: email.trim(), password, phone: phone?.trim() || undefined });
      return await get().signIn(email, password);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to register.";
      set({ error: message });
      throw error;
    }
  },

  async signOut() {
    const currentAccessToken = get().accessToken;
    set({ user: null, accessToken: null, refreshToken: null, status: "unauthenticated" });
    await clearStoredTokens();
    if (currentAccessToken) {
      await unregisterCurrentDevice(currentAccessToken); // never throws; best-effort internally
      try {
        await apiLogout(currentAccessToken);
      } catch {
        // Server-side logout is best-effort; the client session is already cleared either way.
      }
    }
  },

  // Proactively rotates the access token without waiting for a 401 — call
  // this on an interval while authenticated so a session left open longer
  // than the access token's TTL doesn't suddenly start failing requests.
  async refreshSession() {
    const currentRefreshToken = get().refreshToken;
    if (!currentRefreshToken) return;
    try {
      const refreshed = await apiRefresh(currentRefreshToken);
      await persistTokens(refreshed);
      set({ accessToken: refreshed.access_token, refreshToken: refreshed.refresh_token });
    } catch {
      // The refresh token itself has expired — the session is genuinely
      // over; the next authenticated request will surface this properly.
      await get().signOut();
    }
  },

  // Lets a screen (e.g. the profile editor) push a freshly-updated user
  // object into the store after a successful PATCH, so every other screen
  // reading `user` reflects the change immediately without a full re-fetch.
  setUser(user) {
    set({ user });
  },
}));
