import { apiFetch } from "./apiClient";

// Maps & Location System Phase 8/9 — Reverse Geocoding and Forward
// Geocoding / Address Search. Proxied through the backend
// (app/api/v1/customer/location.py), which calls Photon (open-source,
// OSM-based), never Google Places/Geocoding — no API key is involved
// on this client at all.

export type PlaceSearchResult = {
  label: string;
  address_line: string | null;
  city: string | null;
  district: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  latitude: number;
  longitude: number;
  formatted_address: string;
  place_id: string | null;
};

export function searchPlaces(accessToken: string, query: string) {
  return apiFetch<{ results: PlaceSearchResult[] }>(
    `/api/v1/customer/location/search?q=${encodeURIComponent(query)}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
}

export function reverseGeocode(accessToken: string, latitude: number, longitude: number) {
  return apiFetch<{ result: PlaceSearchResult | null }>(
    `/api/v1/customer/location/reverse?lat=${latitude}&lon=${longitude}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
}
