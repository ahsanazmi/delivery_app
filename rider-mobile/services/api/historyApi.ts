import { apiFetch } from "./apiClient";
import type { DeliveryDetail } from "./deliveriesApi";
import type { RiderOrder } from "./riderApi";

export type RiderHistoryStatus = Extract<RiderOrder["status"], "delivered" | "cancelled">;

export type RiderHistoryItem = {
  order_id: string;
  order_number: string;
  restaurant_name: string;
  date: string;
  status: RiderHistoryStatus;
  earning: number | string;
  payment_method: string;
};

export type RiderHistoryFilters = {
  status?: RiderHistoryStatus;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  limit?: number;
};

export function listRiderHistory(accessToken: string, filters: RiderHistoryFilters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  params.set("page", String(filters.page ?? 1));
  params.set("limit", String(filters.limit ?? 20));

  return apiFetch<RiderHistoryItem[]>(`/api/v1/rider/history?${params.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getRiderHistoryDetail(accessToken: string, orderId: string) {
  return apiFetch<DeliveryDetail>(`/api/v1/rider/history/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
