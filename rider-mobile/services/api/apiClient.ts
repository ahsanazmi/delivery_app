import Constants from "expo-constants";
import { Platform } from "react-native";

function getAutoApiBaseUrl(): string {
  const configured = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (configured) return configured;

  const hostUri =
    (Constants as any)?.expoConfig?.hostUri ??
    (Constants as any)?.expoGoConfig?.hostUri ??
    (Constants as any)?.manifest2?.extra?.expoGo?.hostUri;

  if (hostUri) {
    const host = String(hostUri).split(":")[0];
    return `http://${host}:8000`;
  }

  if (Platform.OS === "android") return "http://10.0.2.2:8000";
  return "http://localhost:8000";
}

export const API_BASE = getAutoApiBaseUrl();

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorResponse = { detail?: string };

// A rider's connection can drop for a moment (elevator, tunnel, moving
// between cell towers) and recover a second later. GET requests are always
// safe to retry — they have no side effect to duplicate — so a single
// automatic retry after a short delay turns a lot of these into invisible
// blips instead of a screen full of red error text the rider has to notice
// and manually retry. POST/PATCH/DELETE are deliberately NOT auto-retried
// here: several of them are safe to retry (Phase 28 made accept/pickup/
// start/complete/cod-collect idempotent specifically so a rider's own manual
// re-tap is never dangerous), but a handful of others were never audited
// for that guarantee, and silently retrying every mutating call by default
// isn't worth that risk for what's already a rare failure mode with an
// existing manual-retry path (the on-screen Retry button / re-tapping the
// action) once the request actually reaches the user's error handler.
const NETWORK_RETRY_DELAY_MS = 1000;

function isNetworkFailure(error: unknown): boolean {
  // fetch() rejects (rather than resolving with a non-ok response) only for
  // network-level failures — DNS, connection refused, timeout — never for
  // a real HTTP error status, which is exactly the class of failure a retry
  // a moment later can plausibly fix.
  return error instanceof TypeError || (error instanceof Error && error.message === "Network request failed");
}

async function rawFetch(path: string, init: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init.headers },
  });
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  let response: Response;
  try {
    response = await rawFetch(path, init);
  } catch (err) {
    if (method === "GET" && isNetworkFailure(err)) {
      await new Promise((resolve) => setTimeout(resolve, NETWORK_RETRY_DELAY_MS));
      try {
        response = await rawFetch(path, init);
      } catch {
        throw new ApiError(
          "Unable to reach the server. Check that the API is running and the API URL is correct.",
          0,
        );
      }
    } else {
      throw new ApiError(
        "Unable to reach the server. Check that the API is running and the API URL is correct.",
        0,
      );
    }
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse;
    throw new ApiError(
      body.detail ?? "Something went wrong. Please try again.",
      response.status,
    );
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}
