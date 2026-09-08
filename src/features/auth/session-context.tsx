import * as SecureStore from "expo-secure-store";
import {
    createContext,
    PropsWithChildren,
    useContext,
    useEffect,
    useMemo,
    useState,
} from "react";

import {
    AuthUser,
    getCurrentUser,
    login,
    logout,
    refreshAccessToken,
    register,
    TokenPair,
} from "@/services/api/authApi";

type AuthStatus = "anonymous" | "loading" | "authenticated";

type SessionContextValue = {
  user: AuthUser | null;
  status: AuthStatus;
  accessToken: string | null;
  signIn: (email: string, password: string) => Promise<AuthUser>;
  signUp: (input: {
    fullName: string;
    email: string;
    password: string;
    phone?: string;
  }) => Promise<AuthUser>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const ACCESS_TOKEN_KEY = "say-hi-chai-access-token";
const REFRESH_TOKEN_KEY = "say-hi-chai-refresh-token";

const SessionContext = createContext<SessionContextValue | null>(null);

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
  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    token_type: "bearer",
  };
}

async function loadSession(tokens: TokenPair): Promise<AuthUser> {
  return getCurrentUser(tokens.access_token);
}

export function SessionProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [accessToken, setAccessToken] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function hydrateSession() {
      try {
        const stored = await readStoredTokens();
        if (!stored) {
          if (isMounted) setStatus("anonymous");
          return;
        }

        try {
          const authenticatedUser = await loadSession(stored);
          if (!isMounted) return;
          setUser(authenticatedUser);
          setAccessToken(stored.access_token);
          setStatus("authenticated");
        } catch {
          const refreshed = await refreshAccessToken(stored.refresh_token);
          await persistTokens(refreshed);
          const authenticatedUser = await loadSession(refreshed);
          if (!isMounted) return;
          setUser(authenticatedUser);
          setAccessToken(refreshed.access_token);
          setStatus("authenticated");
        }
      } catch {
        if (isMounted) {
          setUser(null);
          setAccessToken(null);
          setStatus("anonymous");
          void clearStoredTokens();
        }
      }
    }

    void hydrateSession();
    return () => {
      isMounted = false;
    };
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      user,
      status,
      accessToken,
      async signIn(email, password) {
        setStatus("loading");
        try {
          const tokens = await login(email.trim(), password);
          await persistTokens(tokens);
          const authenticatedUser = await loadSession(tokens);
          setAccessToken(tokens.access_token);
          setUser(authenticatedUser);
          setStatus("authenticated");
          return authenticatedUser;
        } catch (error) {
          setStatus("anonymous");
          setAccessToken(null);
          await clearStoredTokens();
          throw error;
        }
      },
      async signUp({ fullName, email, password, phone }) {
        setStatus("loading");
        try {
          await register({
            name: fullName.trim(),
            email: email.trim(),
            password,
            phone: phone?.trim() || undefined,
          });
          const tokens = await login(email.trim(), password);
          await persistTokens(tokens);
          const authenticatedUser = await loadSession(tokens);
          setAccessToken(tokens.access_token);
          setUser(authenticatedUser);
          setStatus("authenticated");
          return authenticatedUser;
        } catch (error) {
          setStatus("anonymous");
          setAccessToken(null);
          await clearStoredTokens();
          throw error;
        }
      },
      async signOut() {
        const currentAccessToken = accessToken;
        setUser(null);
        setAccessToken(null);
        setStatus("anonymous");
        await clearStoredTokens();
        if (currentAccessToken) {
          try {
            await logout(currentAccessToken);
          } catch {
            // Server-side logout is optional; client-side session is still cleared.
          }
        }
      },
      async refresh() {
        if (!accessToken) return;
        try {
          const latest = await getCurrentUser(accessToken);
          setUser(latest);
        } catch {
          // ignore errors; caller can handle sign-out if necessary
        }
      },
    }),
    [accessToken, status, user],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context)
    throw new Error("useSession must be used inside SessionProvider");
  return context;
}
