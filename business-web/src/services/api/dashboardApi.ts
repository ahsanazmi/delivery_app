import { apiFetch } from "@/services/api/apiClient";

export type OrderStatus =
  | "placed"
  | "confirmed"
  | "preparing"
  | "ready_for_pickup"
  | "rider_assigned"
  | "picked_up"
  | "out_for_delivery"
  | "delivered"
  | "cancelled"
  | "rejected";

export type RestaurantOrderSummary = {
  id: string;
  order_number: string;
  status: OrderStatus;
  customer_name: string;
  total: number | string;
  item_count: number;
  created_at: string;
};

export type RestaurantDashboard = {
  restaurant_id: string;
  restaurant_name: string;
  is_open: boolean;

  today_orders_count: number;
  pending_orders_count: number;
  preparing_orders_count: number;
  ready_orders_count: number;
  completed_orders_count: number;

  today_sales: number | string;
  pending_earnings: number | string;

  pending_orders: RestaurantOrderSummary[];
  recent_orders: RestaurantOrderSummary[];
};

export function getRestaurantDashboard(accessToken: string, restaurantId?: string) {
  const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : "";
  return apiFetch<RestaurantDashboard>(`/api/v1/restaurant/dashboard${suffix}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
