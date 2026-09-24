import { apiFetch } from "./apiClient";

export type Address = {
  id: string;
  user_id: string;
  label: string;
  recipient_name: string;
  phone: string;
  address_line: string;
  city: string;
  // Maps & Location System Phase 2 — nullable, matches the backend's own
  // Address model addition: rural/village addresses in this market are
  // often identified by district rather than city alone.
  district: string | null;
  state: string;
  postal_code: string;
  landmark: string | null;
  latitude: number | null;
  longitude: number | null;
  // Maps & Location System Phase 2 — populated by reverse geocoding
  // (Phase 8) or Places search (Phase 9); null for any address entered
  // manually without ever touching the map.
  formatted_address: string | null;
  place_id: string | null;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AddressPayload = {
  label?: string;
  recipient_name: string;
  phone: string;
  address_line: string;
  city: string;
  district?: string | null;
  state: string;
  postal_code: string;
  landmark?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  formatted_address?: string | null;
  place_id?: string | null;
  is_default?: boolean;
};

export function listAddresses(accessToken: string) {
  return apiFetch<Address[]>("/api/v1/addresses", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAddress(accessToken: string, addressId: string) {
  return apiFetch<Address>(`/api/v1/addresses/${addressId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createAddress(accessToken: string, payload: AddressPayload) {
  return apiFetch<Address>("/api/v1/addresses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateAddress(
  accessToken: string,
  addressId: string,
  payload: Partial<AddressPayload>,
) {
  return apiFetch<Address>(`/api/v1/addresses/${addressId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function setDefaultAddress(accessToken: string, addressId: string) {
  return apiFetch<Address>(`/api/v1/addresses/${addressId}/default`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function deleteAddress(accessToken: string, addressId: string) {
  return apiFetch<Address>(`/api/v1/addresses/${addressId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
