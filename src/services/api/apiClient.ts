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

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError(
      "Unable to reach the server. Check that the API is running and the API URL is correct.",
      0,
    );
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ErrorResponse;
    throw new ApiError(
      body.detail ?? "Something went wrong. Please try again.",
      response.status,
    );
  }

  return response.json() as Promise<T>;
}

export async function createOrder(payload: any, accessToken?: string) {
  return apiFetch("/api/v1/orders", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(payload),
  });
}
