import { createContext, type PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

import { AuthUser, getCurrentUser, login, logout, refreshAccessToken, TokenPair } from "@/services/api/authApi";

type AuthStatus = "anonymous" | "loading" | "authenticated";

type SessionContextValue = {
  user: AuthUser | null;
  status: AuthStatus;
  accessToken: string | null;
  signIn: (email: string, password: string) => Promise<AuthUser>;
  signOut: () => Promise<void>;
};

const ACCESS_TOKEN_KEY = "say-hi-chai-admin-access-token";
const REFRESH_TOKEN_KEY = "say-hi-chai-admin-refresh-token";
// The backend issues access tokens with a 15-minute lifetime — refresh well
// before that so a tab left open never sees a request fail with 401 (there's
// no retry-on-401 wired into apiFetch, so without this every call would just
// keep failing until the page was manually reloaded). Mirrors business-web's
// own session-context.tsx, which already had this; admin-web was missing it.
const PROACTIVE_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

const SessionContext = createContext<SessionContextValue | null>(null);

function persistTokens(tokens: TokenPair) {
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
}

function clearStoredTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function readStoredTokens(): TokenPair | null {
  const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!accessToken || !refreshToken) return null;
  return { access_token: accessToken, refresh_token: refreshToken, token_type: "bearer" };
}

export function SessionProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [accessToken, setAccessToken] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function hydrateSession() {
      const stored = readStoredTokens();
      if (!stored) {
        if (isMounted) setStatus("anonymous");
        return;
      }
      try {
        const authenticatedUser = await getCurrentUser(stored.access_token);
        if (!isMounted) return;
        setUser(authenticatedUser);
        setAccessToken(stored.access_token);
        setStatus("authenticated");
      } catch {
        try {
          const refreshed = await refreshAccessToken(stored.refresh_token);
          persistTokens(refreshed);
          const authenticatedUser = await getCurrentUser(refreshed.access_token);
          if (!isMounted) return;
          setUser(authenticatedUser);
          setAccessToken(refreshed.access_token);
          setStatus("authenticated");
        } catch {
          if (isMounted) {
            setUser(null);
            setAccessToken(null);
            setStatus("anonymous");
          }
          clearStoredTokens();
        }
      }
    }

    void hydrateSession();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (status !== "authenticated") return;

    const interval = setInterval(async () => {
      const stored = readStoredTokens();
      if (!stored) return;
      try {
        const refreshed = await refreshAccessToken(stored.refresh_token);
        persistTokens(refreshed);
        setAccessToken(refreshed.access_token);
      } catch {
        // The refresh token itself is gone/expired — nothing to do but sign
        // out; the next action the admin takes will send them to /login.
        setUser(null);
        setAccessToken(null);
        setStatus("anonymous");
        clearStoredTokens();
      }
    }, PROACTIVE_REFRESH_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [status]);

  const value = useMemo<SessionContextValue>(
    () => ({
      user,
      status,
      accessToken,
      async signIn(email, password) {
        setStatus("loading");
        try {
          const tokens = await login(email.trim(), password);
          persistTokens(tokens);
          const authenticatedUser = await getCurrentUser(tokens.access_token);
          setAccessToken(tokens.access_token);
          setUser(authenticatedUser);
          setStatus("authenticated");
          return authenticatedUser;
        } catch (error) {
          setStatus("anonymous");
          setAccessToken(null);
          clearStoredTokens();
          throw error;
        }
      },
      async signOut() {
        const currentAccessToken = accessToken;
        setUser(null);
        setAccessToken(null);
        setStatus("anonymous");
        clearStoredTokens();
        if (currentAccessToken) {
          try {
            await logout(currentAccessToken);
          } catch {
            // Server-side logout is optional; client-side session is still cleared.
          }
        }
      },
    }),
    [accessToken, status, user],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside SessionProvider");
  return context;
}
