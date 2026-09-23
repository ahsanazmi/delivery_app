import { apiFetch } from "./apiClient";

export type VehicleType = "BIKE" | "SCOOTER" | "BICYCLE" | "OTHER";

export type RiderVehicle = {
  vehicle_type: VehicleType | null;
  vehicle_number: string | null;
  vehicle_model: string | null;
  updated_at: string;
};

export type RiderVehicleUpdate = {
  vehicle_type?: VehicleType;
  vehicle_number?: string;
  vehicle_model?: string;
};

export function getRiderVehicle(accessToken: string) {
  return apiFetch<RiderVehicle>("/api/v1/rider/vehicle", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateRiderVehicle(accessToken: string, payload: RiderVehicleUpdate) {
  return apiFetch<RiderVehicle>("/api/v1/rider/vehicle", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify(payload),
  });
}
