import { apiFetch } from "./apiClient";

// Maps & Location System Phase 9 — Forward Geocoding / Address Search.
// Proxied through the backend (app/api/v1/customer/location.py), which
// calls Photon (open-source, OSM-based), never Google Places — no API
// key is involved on this client at all.

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
