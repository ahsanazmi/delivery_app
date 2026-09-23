import { apiFetch } from "./apiClient";

export type SettlementType = "PAYOUT" | "REMITTANCE";

export type RiderSettlement = {
  id: string;
  settlement_type: SettlementType;
  amount: number | string;
  note: string | null;
  created_at: string;
};

export type RiderWallet = {
  total_earnings: number | string;
  total_cod_collected: number | string;
  total_settled: number | string;
  wallet_balance: number | string;
  settlement_due: number | string;
};

export function getRiderWallet(accessToken: string) {
  return apiFetch<RiderWallet>("/api/v1/rider/wallet", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Rider Payment/COD Visibility (Phase 29) — "Settlement information
// relevant to the rider": each row is a real, already-scoped-to-this-
// rider movement of money between the rider and the platform (PAYOUT the
// platform paid out, or REMITTANCE the rider paid in to clear COD debt),
// never another rider's.
export function listRiderSettlements(accessToken: string, options: { page?: number; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (options.page) params.set("page", String(options.page));
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return apiFetch<RiderSettlement[]>(`/api/v1/rider/wallet/settlements${query ? `?${query}` : ""}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
