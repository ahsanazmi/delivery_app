import { apiFetch } from "./apiClient";

export type EarningType = "DELIVERY_FEE" | "INCENTIVE" | "BONUS" | "ADJUSTMENT";

export type RiderEarning = {
  id: string;
  order_id: string | null;
  earning_type: EarningType;
  amount: number | string;
  description: string | null;
  created_at: string;
};

export type EarningsBreakdown = {
  delivery_fee: number | string;
  incentive: number | string;
  bonus: number | string;
  adjustment: number | string;
  total: number | string;
};

export type RiderEarningsSummary = {
  today: EarningsBreakdown;
  week: EarningsBreakdown;
  month: EarningsBreakdown;
  total_deliveries: number;
  average_earning: number | string;
};

export function listRiderEarnings(accessToken: string) {
  return apiFetch<RiderEarning[]>("/api/v1/rider/earnings", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getRiderEarningsSummary(accessToken: string) {
  return apiFetch<RiderEarningsSummary>("/api/v1/rider/earnings/summary", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
