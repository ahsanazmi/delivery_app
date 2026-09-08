import { apiFetch } from "./apiClient";

export type AdminDashboard = {
  total_orders: number;
  pending_orders: number;
  total_customers: number;
  active_restaurants: number;
};

export type AdminOrderStatus =
  | "pending"
  | "confirmed"
  | "preparing"
  | "out_for_delivery"
  | "delivered"
  | "cancelled";

export type AdminOrder = {
  id: string;
  user_id: string;
  restaurant_id: string | null;
  restaurant_name: string | null;
  restaurant_phone: string | null;
  order_number: string;
  status: AdminOrderStatus;
  payment_method: string;
  subtotal: string;
  delivery_fee: string;
  total: string;
  item_count: number;
  address_line: string;
  city: string;
  state: string | null;
  postal_code: string;
  landmark: string | null;
  latitude: number | null;
  longitude: number | null;
  delivery_instructions: string | null;
  cancelled_reason: string | null;
  is_paid: boolean;
  created_at: string;
  updated_at: string;
};

export function getAdminDashboard(accessToken: string) {
  return apiFetch<AdminDashboard>("/api/v1/admin/dashboard", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminOrders(accessToken: string) {
  return apiFetch<AdminOrder[]>("/api/v1/admin/orders", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminCustomers(accessToken: string) {
  return apiFetch<any[]>("/api/v1/admin/customers", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRiders(accessToken: string) {
  return apiFetch<any[]>("/api/v1/admin/riders", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function assignRiderToOrder(
  accessToken: string,
  orderId: string,
  riderId: string,
) {
  return apiFetch<AdminOrder>(
    `/api/v1/admin/orders/${orderId}/assign-rider?rider_id=${encodeURIComponent(riderId)}`,
    {
      method: "PATCH",
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  );
}

export function updateAdminOrderStatus(
  accessToken: string,
  orderId: string,
  status: AdminOrderStatus,
  note?: string,
) {
  return apiFetch<AdminOrder>(`/api/v1/admin/orders/${orderId}/status`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ status, note }),
  });
}
