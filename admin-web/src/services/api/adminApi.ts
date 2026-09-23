import { apiFetch } from "./apiClient";

export type AdminDashboardSummary = {
  total_customers: number;
  total_restaurants: number;
  active_restaurants: number;
  total_riders: number;
  active_riders: number;
  todays_orders: number;
  todays_revenue: string;
  pending_orders: number;
  pending_rider_approvals: number;
  pending_restaurant_approvals: number;
  pending_cod_settlement: string;
};

export type AdminRecentOrder = {
  id: string;
  order_number: string;
  restaurant_name: string | null;
  customer_name: string;
  status: AdminOrderStatus;
  total: string;
  created_at: string;
};

export type AdminRecentRegistration = {
  id: string;
  name: string;
  role: "CUSTOMER" | "RIDER" | "RESTAURANT_OWNER" | "ADMIN";
  created_at: string;
};

export type AdminPendingApproval = {
  id: string;
  name: string;
  email: string | null;
  type: "rider";
  submitted_at: string;
};

export type AdminOperationalAlert = {
  severity: "info" | "warning" | "critical";
  message: string;
  count: number;
  // Phase 24 — a relative admin-web path this alert navigates to on click.
  link: string;
};

export type AdminDashboardResponse = {
  summary: AdminDashboardSummary;
  recent_orders: AdminRecentOrder[];
  recent_registrations: AdminRecentRegistration[];
  pending_approvals: AdminPendingApproval[];
  alerts: AdminOperationalAlert[];
};

export type AdminOrderStatus =
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
  return apiFetch<AdminDashboardResponse>("/api/v1/admin/dashboard", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type AdminOrderSummary = {
  id: string;
  order_number: string;
  customer_name: string;
  restaurant_name: string | null;
  rider_name: string | null;
  status: AdminOrderStatus;
  payment_method: string;
  payment_status: string;
  subtotal: string;
  delivery_fee: string;
  tax: string;
  discount: string;
  total: string;
  created_at: string;
};

export type AdminOrderListResponse = {
  items: AdminOrderSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminOrderItem = {
  id: string;
  product_id: string;
  product_name: string;
  unit_price: string;
  quantity: number;
};

export type AdminOrderStatusHistoryEntry = {
  id: string;
  status: AdminOrderStatus;
  note: string | null;
  created_at: string;
};

export type AdminOrderDetail = AdminOrderSummary & {
  customer_email: string;
  customer_phone: string | null;
  restaurant_phone: string | null;
  restaurant_address: string | null;
  items: AdminOrderItem[];
  status_history: AdminOrderStatusHistoryEntry[];
};

export type AdminOrderListParams = {
  search?: string;
  status?: AdminOrderStatus;
  payment_method?: string;
  payment_status?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
};

export function getAdminOrders(accessToken: string, params: AdminOrderListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.payment_method) query.set("payment_method", params.payment_method);
  if (params.payment_status) query.set("payment_status", params.payment_status);
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminOrderListResponse>(`/api/v1/admin/orders?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminOrderDetail(accessToken: string, orderId: string) {
  return apiFetch<AdminOrderDetail>(`/api/v1/admin/orders/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type AdminCustomerStatus = "ACTIVE" | "SUSPENDED";

export type AdminCustomerSummary = {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  status: AdminCustomerStatus;
  created_at: string;
  order_count: number;
  total_spending: string;
};

export type AdminCustomerListResponse = {
  items: AdminCustomerSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminCustomerDetail = AdminCustomerSummary & {
  recent_orders: AdminRecentOrder[];
};

export type AdminCustomerListParams = {
  search?: string;
  status?: AdminCustomerStatus;
  registered_after?: string;
  registered_before?: string;
  page?: number;
  limit?: number;
};

export function getAdminCustomers(accessToken: string, params: AdminCustomerListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.registered_after) query.set("registered_after", params.registered_after);
  if (params.registered_before) query.set("registered_before", params.registered_before);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminCustomerListResponse>(`/api/v1/admin/customers?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminCustomerDetail(accessToken: string, customerId: string) {
  return apiFetch<AdminCustomerDetail>(`/api/v1/admin/customers/${customerId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 23 — replaces the old PATCH-with-status call with two explicit,
// reason-requiring, audited actions.
export function suspendAdminCustomer(accessToken: string, customerId: string, reason: string) {
  return apiFetch<AdminCustomerDetail>(`/api/v1/admin/customers/${customerId}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason }),
  });
}

export function activateAdminCustomer(accessToken: string, customerId: string, reason: string) {
  return apiFetch<AdminCustomerDetail>(`/api/v1/admin/customers/${customerId}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason }),
  });
}

export type AdminRestaurantStatus = "ACTIVE" | "INACTIVE";
export type AdminApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "SUSPENDED";

export type AdminMenuItem = {
  id: string;
  name: string;
  price: string;
  is_active: boolean;
};

export type AdminRestaurantSummary = {
  id: string;
  name: string;
  phone: string;
  email: string | null;
  owner_id: string;
  owner_name: string;
  status: AdminRestaurantStatus;
  approval_status: AdminApprovalStatus;
  rejection_reason: string | null;
  is_open: boolean;
  average_rating: string;
  created_at: string;
  order_count: number;
  total_revenue: string;
};

export type AdminRestaurantListResponse = {
  items: AdminRestaurantSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminRestaurantDetail = AdminRestaurantSummary & {
  owner_email: string | null;
  owner_phone: string | null;
  menu: AdminMenuItem[];
  recent_orders: AdminRecentOrder[];
};

export type AdminRestaurantListParams = {
  search?: string;
  status?: AdminRestaurantStatus;
  is_open?: boolean;
  approval_status?: AdminApprovalStatus;
  page?: number;
  limit?: number;
};

export function getAdminRestaurants(accessToken: string, params: AdminRestaurantListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.is_open !== undefined) query.set("is_open", String(params.is_open));
  if (params.approval_status) query.set("approval_status", params.approval_status);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminRestaurantListResponse>(`/api/v1/admin/restaurants?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRestaurantDetail(accessToken: string, restaurantId: string) {
  return apiFetch<AdminRestaurantDetail>(`/api/v1/admin/restaurants/${restaurantId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function postRestaurantAction(accessToken: string, restaurantId: string, action: string, body?: object) {
  return apiFetch<AdminRestaurantDetail>(`/api/v1/admin/restaurants/${restaurantId}/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// Admin Intervention Validation (Phase 21) — approve/suspend/activate now
// require a reason, same as reject/deactivate/reactivate already did, so
// every administrative intervention here is auditable.
export function approveAdminRestaurant(accessToken: string, restaurantId: string, reason: string) {
  return postRestaurantAction(accessToken, restaurantId, "approve", { reason });
}

export function rejectAdminRestaurant(accessToken: string, restaurantId: string, rejectionReason: string) {
  return postRestaurantAction(accessToken, restaurantId, "reject", { rejection_reason: rejectionReason });
}

export function suspendAdminRestaurant(accessToken: string, restaurantId: string, reason: string) {
  return postRestaurantAction(accessToken, restaurantId, "suspend", { reason });
}

export function activateAdminRestaurant(accessToken: string, restaurantId: string, reason: string) {
  return postRestaurantAction(accessToken, restaurantId, "activate", { reason });
}

// Phase 23 — the is_active-based on/off switch, distinct from the
// approval-status suspend/activate above (Phase 6). Named deactivate/
// reactivate since suspend/activate are already taken. Replaces the old
// PATCH-with-status call.
export function deactivateAdminRestaurant(accessToken: string, restaurantId: string, reason: string) {
  return postRestaurantAction(accessToken, restaurantId, "deactivate", { reason });
}

export function reactivateAdminRestaurant(accessToken: string, restaurantId: string, reason: string) {
  return postRestaurantAction(accessToken, restaurantId, "reactivate", { reason });
}

export type AdminRestaurantOwnerStatus = "ACTIVE" | "SUSPENDED";

export type AdminOwnedRestaurant = {
  id: string;
  name: string;
  is_active: boolean;
  approval_status: AdminApprovalStatus;
};

export type AdminRestaurantOwnerSummary = {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  status: AdminRestaurantOwnerStatus;
  created_at: string;
  restaurants: AdminOwnedRestaurant[];
};

export type AdminRestaurantOwnerListResponse = {
  items: AdminRestaurantOwnerSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminRestaurantOwnerListParams = {
  search?: string;
  status?: AdminRestaurantOwnerStatus;
  has_restaurant?: boolean;
  page?: number;
  limit?: number;
};

export function getAdminRestaurantOwners(accessToken: string, params: AdminRestaurantOwnerListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.has_restaurant !== undefined) query.set("has_restaurant", String(params.has_restaurant));
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminRestaurantOwnerListResponse>(`/api/v1/admin/restaurant-owners?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRestaurantOwnerDetail(accessToken: string, ownerId: string) {
  return apiFetch<AdminRestaurantOwnerSummary>(`/api/v1/admin/restaurant-owners/${ownerId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 23 — replaces the old PATCH-with-status call with two explicit,
// reason-requiring, audited actions.
export function suspendAdminRestaurantOwner(accessToken: string, ownerId: string, reason: string) {
  return apiFetch<AdminRestaurantOwnerSummary>(`/api/v1/admin/restaurant-owners/${ownerId}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason }),
  });
}

export function activateAdminRestaurantOwner(accessToken: string, ownerId: string, reason: string) {
  return apiFetch<AdminRestaurantOwnerSummary>(`/api/v1/admin/restaurant-owners/${ownerId}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason }),
  });
}

export type AdminRiderVehicleType = "BIKE" | "SCOOTER" | "BICYCLE" | "OTHER";

export type AdminRiderDocument = {
  id: string;
  document_type: string;
  document_number: string | null;
  document_url: string;
  verification_status: "PENDING" | "APPROVED" | "REJECTED";
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type AdminRiderDelivery = {
  id: string;
  order_number: string;
  restaurant_name: string | null;
  status: AdminOrderStatus;
  total: string;
  created_at: string;
};

export type AdminRiderSummary = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  approval_status: AdminApprovalStatus;
  rejection_reason: string | null;
  is_online: boolean;
  vehicle_type: AdminRiderVehicleType | null;
  vehicle_number: string | null;
  rating: number;
  deliveries_count: number;
  total_earnings: string;
  created_at: string;
  // Phase 23 — account-level on/off switch (User.is_active), distinct
  // from approval_status (delivery eligibility only).
  is_active: boolean;
};

export type AdminRiderListResponse = {
  items: AdminRiderSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminRiderDetail = AdminRiderSummary & {
  documents: AdminRiderDocument[];
  recent_deliveries: AdminRiderDelivery[];
};

export type AdminRiderListParams = {
  search?: string;
  approval_status?: AdminApprovalStatus;
  is_online?: boolean;
  page?: number;
  limit?: number;
};

export function getAdminRiders(accessToken: string, params: AdminRiderListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.approval_status) query.set("approval_status", params.approval_status);
  if (params.is_online !== undefined) query.set("is_online", String(params.is_online));
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminRiderListResponse>(`/api/v1/admin/riders?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRiderDetail(accessToken: string, riderId: string) {
  return apiFetch<AdminRiderDetail>(`/api/v1/admin/riders/${riderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type AdminRiderApprovalActionName = "approve" | "reject" | "suspend" | "activate";

// Phase 9 — calls the dedicated POST /riders/{id}/<action> endpoints
// (mirroring the restaurant approval actions) rather than the generic
// PATCH /riders/{id}; both exist server-side, but these per-action routes
// are the canonical ones this phase introduced.
// Admin Intervention Validation (Phase 21) — every action now requires a
// reason, not just reject, so every administrative intervention here is
// auditable (see record_admin_audit_log on the backend).
export function updateAdminRiderApproval(
  accessToken: string,
  riderId: string,
  action: AdminRiderApprovalActionName,
  reason: string,
) {
  return apiFetch<AdminRiderDetail>(`/api/v1/admin/riders/${riderId}/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(action === "reject" ? { rejection_reason: reason } : { reason }),
  });
}

// Phase 23 — the account-level on/off switch (User.is_active), a new
// capability distinct from the approval_status suspend/activate above.
// Named deactivate/reactivate since suspend/activate are already taken.
export function deactivateAdminRider(accessToken: string, riderId: string, reason: string) {
  return apiFetch<AdminRiderDetail>(`/api/v1/admin/riders/${riderId}/deactivate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason }),
  });
}

export function reactivateAdminRider(accessToken: string, riderId: string, reason: string) {
  return apiFetch<AdminRiderDetail>(`/api/v1/admin/riders/${riderId}/reactivate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason }),
  });
}

export function getAdminRiderDocuments(accessToken: string, riderId: string) {
  return apiFetch<AdminRiderDocument[]>(`/api/v1/admin/riders/${riderId}/documents`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function approveAdminRiderDocument(accessToken: string, riderId: string, documentId: string) {
  return apiFetch<AdminRiderDocument>(`/api/v1/admin/riders/${riderId}/documents/${documentId}/approve`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function rejectAdminRiderDocument(accessToken: string, riderId: string, documentId: string, rejectionReason: string) {
  return apiFetch<AdminRiderDocument>(`/api/v1/admin/riders/${riderId}/documents/${documentId}/reject`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ rejection_reason: rejectionReason }),
  });
}

// Order State Rule — assign-rider is exclusively an admin action, so it
// now requires a reason and is audited server-side, same as
// cancelAdminOrder/reassignAdminOrderRider below.
export function assignRiderToOrder(
  accessToken: string,
  orderId: string,
  riderId: string,
  reason: string,
) {
  return apiFetch<AdminOrder>(`/api/v1/admin/orders/${orderId}/assign-rider`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ rider_id: riderId, reason }),
  });
}

// Phase 11 — the generic PATCH /orders/{id}/status this used to call was
// removed server-side ("do NOT allow arbitrary direct status
// modification"); cancelAdminOrder/reassignAdminOrderRider below are its
// explicit, audited replacements for the one transition with a clear
// business rule (cancellation) plus the other named intervention.
export function cancelAdminOrder(accessToken: string, orderId: string, reason: string) {
  return apiFetch<AdminOrder>(`/api/v1/admin/orders/${orderId}/cancel`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ reason }),
  });
}

export function reassignAdminOrderRider(accessToken: string, orderId: string, newRiderId: string, reason: string) {
  return apiFetch<AdminOrder>(`/api/v1/admin/orders/${orderId}/reassign-rider`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ new_rider_id: newRiderId, reason }),
  });
}

// Phase 12 — view-only. "PENDING" entries are synthesized server-side for
// unclaimed READY_FOR_PICKUP orders (id is null for those — there's no
// real assignment row to link to yet).
export type AdminAssignmentStatusValue =
  | "PENDING"
  | "ACCEPTED"
  | "REJECTED"
  | "ARRIVED_AT_RESTAURANT"
  | "PICKED_UP"
  | "OUT_FOR_DELIVERY"
  | "DELIVERED"
  | "CANCELLED";

export type AdminDeliveryAssignmentSummary = {
  id: string | null;
  order_id: string;
  order_number: string;
  rider_id: string | null;
  rider_name: string | null;
  status: AdminAssignmentStatusValue;
  accepted_at: string | null;
  picked_up_at: string | null;
  delivered_at: string | null;
  created_at: string;
};

export type AdminDeliveryAssignmentListResponse = {
  items: AdminDeliveryAssignmentSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminDeliveryAssignmentDetail = AdminDeliveryAssignmentSummary & {
  restaurant_name: string | null;
  customer_name: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  arrived_at: string | null;
  out_for_delivery_at: string | null;
  cancelled_at: string | null;
  updated_at: string;
};

export type AdminDeliveryAssignmentListParams = {
  search?: string;
  status?: AdminAssignmentStatusValue;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
};

export function getAdminDeliveryAssignments(accessToken: string, params: AdminDeliveryAssignmentListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminDeliveryAssignmentListResponse>(`/api/v1/admin/delivery-assignments?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminDeliveryAssignmentDetail(accessToken: string, assignmentId: string) {
  return apiFetch<AdminDeliveryAssignmentDetail>(`/api/v1/admin/delivery-assignments/${assignmentId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 13 — view-only. Never carries a signature or any provider secret;
// transaction_reference is the most this ever exposes about the payment
// gateway's own side of things.
// Admin Payment Management (Phase 27) — PROCESSING and PARTIALLY_REFUNDED
// were already real, filterable backend statuses since Payment System
// Phase 23, but this list never included them — an admin could never
// actually select either one, even though payments could genuinely be in
// those states. Fixed here alongside the rest of this phase's work.
export type AdminPaymentStatusValue =
  | "PENDING"
  | "PROCESSING"
  | "PAID"
  | "FAILED"
  | "REFUND_PENDING"
  | "PARTIALLY_REFUNDED"
  | "REFUNDED"
  | "CANCELLED";
export type AdminPaymentMethodValue = "razorpay" | "cod";

export type AdminPaymentSummary = {
  id: string;
  order_id: string;
  order_number: string;
  customer_name: string;
  amount: string;
  method: AdminPaymentMethodValue;
  // Admin Payment Management (Phase 27) — the external gateway that
  // actually processed this payment ("Razorpay"), distinct from `method`
  // (the customer's own cod/online choice). null for COD — cash has no
  // external provider at all.
  provider: string | null;
  status: AdminPaymentStatusValue;
  transaction_reference: string | null;
  // Admin Payment Management (Phase 27) — the most recent real refund's
  // own status (pending/processing/completed/failed), or null if this
  // payment has never had a refund attempted.
  latest_refund_status: string | null;
  created_at: string;
  // Admin Payment Management (Phase 27) — when the payment was actually
  // confirmed paid, distinct from created_at. null until it genuinely
  // succeeds.
  paid_at: string | null;
};

export type AdminPaymentListResponse = {
  items: AdminPaymentSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminPaymentDetail = AdminPaymentSummary & {
  customer_email: string;
  currency: string;
  is_verified: boolean;
  failure_reason: string | null;
  collected_by_rider_name: string | null;
  collected_at: string | null;
  updated_at: string;
};

export type AdminPaymentListParams = {
  search?: string;
  method?: AdminPaymentMethodValue;
  status?: AdminPaymentStatusValue;
  date_from?: string;
  date_to?: string;
  // Admin Payment Management (Phase 27) — dedicated Order ID / Customer
  // filters, additive alongside `search` above (unchanged).
  order_number?: string;
  customer?: string;
  page?: number;
  limit?: number;
};

export function getAdminPayments(accessToken: string, params: AdminPaymentListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.method) query.set("method", params.method);
  if (params.status) query.set("status", params.status);
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  if (params.order_number) query.set("order_number", params.order_number);
  if (params.customer) query.set("customer", params.customer);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminPaymentListResponse>(`/api/v1/admin/payments?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminPaymentDetail(accessToken: string, paymentId: string) {
  return apiFetch<AdminPaymentDetail>(`/api/v1/admin/payments/${paymentId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 14 — COD Reconciliation. Settling always creates a new ledger row
// server-side; there is no way to directly edit collected/settled/outstanding.
export type AdminCODSettlementStatus = "PENDING" | "PARTIAL" | "SETTLED";

export type AdminCODReconciliationSummary = {
  rider_id: string;
  rider_name: string;
  cod_collected: string;
  expected_settlement: string;
  settled_amount: string;
  outstanding_amount: string;
  status: AdminCODSettlementStatus;
};

export type AdminCODReconciliationListResponse = {
  items: AdminCODReconciliationSummary[];
  total: number;
  page: number;
  limit: number;
};

// Financial Ledger Validation (Phase 30) — exactly which collected
// order this portion of a settlement discharges, so a settlement is
// never just a lump-sum figure with no way to trace it back to the
// actual cash it accounts for.
export type AdminCODSettlementAllocationRecord = {
  cod_collection_id: string;
  order_id: string;
  order_number: string;
  amount_allocated: string;
  collected_at: string;
};

export type AdminCODSettlementRecord = {
  id: string;
  amount: string;
  note: string | null;
  created_at: string;
  allocations: AdminCODSettlementAllocationRecord[];
};

export type AdminCODReconciliationDetail = AdminCODReconciliationSummary & {
  settlements: AdminCODSettlementRecord[];
};

export type AdminCODReconciliationListParams = {
  search?: string;
  status?: AdminCODSettlementStatus;
  page?: number;
  limit?: number;
};

export function getAdminCODReconciliation(accessToken: string, params: AdminCODReconciliationListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.status) query.set("status", params.status);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminCODReconciliationListResponse>(`/api/v1/admin/cod?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminCODReconciliationDetail(accessToken: string, riderId: string) {
  return apiFetch<AdminCODReconciliationDetail>(`/api/v1/admin/cod/${riderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function settleAdminCOD(accessToken: string, riderId: string, amount: string, note?: string) {
  return apiFetch<AdminCODReconciliationDetail>(`/api/v1/admin/cod/${riderId}/settle`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ amount, note }),
  });
}

// Phase 15 — the platform-wide, home-page cuisine Category, distinct from
// a restaurant's own menu sections (which this admin app never manages).
export type AdminCategory = {
  id: string;
  name: string;
  image_url: string | null;
  display_order: number;
  is_active: boolean;
  restaurant_count: number;
  created_at: string;
  updated_at: string;
};

export type AdminCategoryListResponse = {
  items: AdminCategory[];
  total: number;
  page: number;
  limit: number;
};

export type AdminCategoryListParams = {
  search?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
};

export function getAdminCategories(accessToken: string, params: AdminCategoryListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.is_active !== undefined) query.set("is_active", String(params.is_active));
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 50));

  return apiFetch<AdminCategoryListResponse>(`/api/v1/admin/categories?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createAdminCategory(
  accessToken: string,
  payload: { name: string; image_url?: string; display_order?: number },
) {
  return apiFetch<AdminCategory>("/api/v1/admin/categories", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateAdminCategory(
  accessToken: string,
  categoryId: string,
  payload: { name?: string; image_url?: string; display_order?: number; is_active?: boolean },
) {
  return apiFetch<AdminCategory>(`/api/v1/admin/categories/${categoryId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export async function deleteAdminCategory(accessToken: string, categoryId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/admin/categories/${categoryId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 16 — platform delivery/service-area management. postal_codes is
// always the zone's complete set — an update replaces it, never merges.
export type AdminServiceArea = {
  id: string;
  city: string;
  district: string | null;
  zone_name: string;
  postal_codes: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AdminServiceAreaListResponse = {
  items: AdminServiceArea[];
  total: number;
  page: number;
  limit: number;
};

export type AdminServiceAreaListParams = {
  search?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
};

export function getAdminServiceAreas(accessToken: string, params: AdminServiceAreaListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.is_active !== undefined) query.set("is_active", String(params.is_active));
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 50));

  return apiFetch<AdminServiceAreaListResponse>(`/api/v1/admin/service-areas?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createAdminServiceArea(
  accessToken: string,
  payload: { city: string; district?: string; zone_name: string; postal_codes: string[]; is_active?: boolean },
) {
  return apiFetch<AdminServiceArea>("/api/v1/admin/service-areas", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateAdminServiceArea(
  accessToken: string,
  serviceAreaId: string,
  payload: { city?: string; district?: string | null; zone_name?: string; postal_codes?: string[]; is_active?: boolean },
) {
  return apiFetch<AdminServiceArea>(`/api/v1/admin/service-areas/${serviceAreaId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export async function deleteAdminServiceArea(accessToken: string, serviceAreaId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/admin/service-areas/${serviceAreaId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 18 — the complete admin coupon surface. A separate, pre-existing
// admin coupon endpoint also exists at the bare /api/v1/coupons path; this
// app only ever talks to the new /admin/coupons one.
export type AdminDiscountType = "percent" | "fixed";

export type AdminCoupon = {
  id: string;
  code: string;
  discount_type: AdminDiscountType;
  discount_value: string;
  min_order: string;
  max_discount: string | null;
  start_date: string | null;
  end_date: string | null;
  usage_limit: number | null;
  per_customer_limit: number | null;
  restaurant_id: string | null;
  restaurant_name: string | null;
  is_active: boolean;
  redemption_count: number;
  created_at: string;
  updated_at: string;
};

export type AdminCouponListResponse = {
  items: AdminCoupon[];
  total: number;
  page: number;
  limit: number;
};

export type AdminCouponListParams = {
  search?: string;
  discount_type?: AdminDiscountType;
  is_active?: boolean;
  page?: number;
  limit?: number;
};

export type AdminCouponInput = {
  code?: string;
  discount_type?: AdminDiscountType;
  discount_value?: string;
  min_order?: string;
  max_discount?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  usage_limit?: number | null;
  per_customer_limit?: number | null;
  restaurant_id?: string | null;
  is_active?: boolean;
};

export function getAdminCoupons(accessToken: string, params: AdminCouponListParams = {}) {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.discount_type) query.set("discount_type", params.discount_type);
  if (params.is_active !== undefined) query.set("is_active", String(params.is_active));
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 20));

  return apiFetch<AdminCouponListResponse>(`/api/v1/admin/coupons?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminCouponDetail(accessToken: string, couponId: string) {
  return apiFetch<AdminCoupon>(`/api/v1/admin/coupons/${couponId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createAdminCoupon(accessToken: string, payload: AdminCouponInput) {
  return apiFetch<AdminCoupon>("/api/v1/admin/coupons", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateAdminCoupon(accessToken: string, couponId: string, payload: AdminCouponInput) {
  return apiFetch<AdminCoupon>(`/api/v1/admin/coupons/${couponId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export async function deleteAdminCoupon(accessToken: string, couponId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/admin/coupons/${couponId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 19 — Reports & Analytics. Every number here comes straight from
// the backend; this app never derives an authoritative total from raw
// rows itself.
export type AdminReportDateRangeParams = { date_from?: string; date_to?: string };

export type AdminDailyCount = { date: string; count: number };
export type AdminDailyAmount = { date: string; amount: string };
export type AdminOrderStatusCount = { status: string; count: number };

export type AdminReportsOverview = {
  date_from: string | null;
  date_to: string | null;
  total_orders: number;
  completed_orders: number;
  cancelled_orders: number;
  revenue: string;
  platform_commission: string;
  restaurant_earnings: string;
  rider_earnings: string;
  cod_outstanding: string;
  customer_growth: number;
  restaurant_growth: number;
  rider_growth: number;
};

export type AdminOrdersReport = {
  date_from: string | null;
  date_to: string | null;
  total_orders: number;
  completed_orders: number;
  cancelled_orders: number;
  rejected_orders: number;
  in_progress_orders: number;
  status_breakdown: AdminOrderStatusCount[];
  orders_by_day: AdminDailyCount[];
};

export type AdminRevenueReport = {
  date_from: string | null;
  date_to: string | null;
  revenue: string;
  platform_commission: string;
  restaurant_earnings: string;
  rider_earnings: string;
  revenue_by_day: AdminDailyAmount[];
};

export type AdminTopRestaurant = { restaurant_id: string; restaurant_name: string; order_count: number; revenue: string };

export type AdminRestaurantsReport = {
  date_from: string | null;
  date_to: string | null;
  total_restaurants: number;
  active_restaurants: number;
  new_restaurants: number;
  growth_by_day: AdminDailyCount[];
  top_restaurants: AdminTopRestaurant[];
};

export type AdminTopRider = { rider_id: string; rider_name: string; deliveries_count: number; earnings: string };

export type AdminRidersReport = {
  date_from: string | null;
  date_to: string | null;
  total_riders: number;
  active_riders: number;
  new_riders: number;
  rider_earnings: string;
  cod_outstanding: string;
  growth_by_day: AdminDailyCount[];
  top_riders: AdminTopRider[];
};

export type AdminTopCustomer = { customer_id: string; customer_name: string; order_count: number; total_spent: string };

export type AdminCustomersReport = {
  date_from: string | null;
  date_to: string | null;
  total_customers: number;
  new_customers: number;
  growth_by_day: AdminDailyCount[];
  top_customers: AdminTopCustomer[];
};

function reportQuery(params: AdminReportDateRangeParams): string {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  return query.toString();
}

export function getAdminReportsOverview(accessToken: string, params: AdminReportDateRangeParams = {}) {
  return apiFetch<AdminReportsOverview>(`/api/v1/admin/reports/overview?${reportQuery(params)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminOrdersReport(accessToken: string, params: AdminReportDateRangeParams = {}) {
  return apiFetch<AdminOrdersReport>(`/api/v1/admin/reports/orders?${reportQuery(params)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRevenueReport(accessToken: string, params: AdminReportDateRangeParams = {}) {
  return apiFetch<AdminRevenueReport>(`/api/v1/admin/reports/revenue?${reportQuery(params)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRestaurantsReport(accessToken: string, params: AdminReportDateRangeParams = {}) {
  return apiFetch<AdminRestaurantsReport>(`/api/v1/admin/reports/restaurants?${reportQuery(params)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminRidersReport(accessToken: string, params: AdminReportDateRangeParams = {}) {
  return apiFetch<AdminRidersReport>(`/api/v1/admin/reports/riders?${reportQuery(params)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminCustomersReport(accessToken: string, params: AdminReportDateRangeParams = {}) {
  return apiFetch<AdminCustomersReport>(`/api/v1/admin/reports/customers?${reportQuery(params)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 20 — operational alerts broadcast to every admin (new restaurant/
// rider registration, a submitted document, an order issue, a payment
// failure, a COD settlement due). Reuses the same generic notification
// shape the customer and rider portals already use.
export type AdminNotification = {
  id: string;
  type: string;
  title: string;
  body: string;
  order_id: string | null;
  is_read: boolean;
  created_at: string;
};

export function getAdminNotifications(accessToken: string) {
  return apiFetch<AdminNotification[]>("/api/v1/admin/notifications", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markAdminNotificationRead(accessToken: string, notificationId: string) {
  return apiFetch<AdminNotification>(`/api/v1/admin/notifications/${notificationId}/read`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markAllAdminNotificationsRead(accessToken: string) {
  return apiFetch<{ updated: number }>("/api/v1/admin/notifications/read-all", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 21 — a read-only view over every explicit administrative
// intervention (order cancel/reassign, COD settlement, ...). entity_type/
// entity_id/old_value/new_value are this API's own naming for what the
// backend's AdminAuditLog table calls target_type/target_id/
// previous_state/new_state.
export type AdminAuditLogSummary = {
  id: string;
  admin_id: string;
  admin_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  reason: string;
  ip_address: string | null;
  created_at: string;
};

export type AdminAuditLogDetail = AdminAuditLogSummary & {
  old_value: string | null;
  new_value: string | null;
};

export type AdminAuditLogListResponse = {
  items: AdminAuditLogSummary[];
  total: number;
  page: number;
  limit: number;
};

export type AdminAuditLogListParams = {
  admin_id?: string;
  action?: string;
  entity_type?: string;
  entity_id?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
};

export function getAdminAuditLogs(accessToken: string, params: AdminAuditLogListParams = {}) {
  const query = new URLSearchParams();
  if (params.admin_id) query.set("admin_id", params.admin_id);
  if (params.action) query.set("action", params.action);
  if (params.entity_type) query.set("entity_type", params.entity_type);
  if (params.entity_id) query.set("entity_id", params.entity_id);
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  query.set("page", String(params.page ?? 1));
  query.set("limit", String(params.limit ?? 50));

  return apiFetch<AdminAuditLogListResponse>(`/api/v1/admin/audit-logs?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getAdminAuditLog(accessToken: string, auditLogId: string) {
  return apiFetch<AdminAuditLogDetail>(`/api/v1/admin/audit-logs/${auditLogId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Phase 22 — Admin Settings. "Default commission" is deliberately not a
// field here — it stays owned by the Phase 17 commission endpoints below,
// which Settings.tsx also reads/writes from since no separate Commissions
// page exists yet.
export type AdminPlatformSettings = {
  id: string;
  platform_name: string;
  support_email: string | null;
  support_phone: string | null;
  default_delivery_fee: string;
  default_minimum_order: string;
  notifications_enabled: boolean;
  maintenance_mode: boolean;
  updated_at: string;
};

export type AdminPlatformSettingsUpdate = Partial<{
  platform_name: string;
  support_email: string;
  support_phone: string;
  default_delivery_fee: string;
  default_minimum_order: string;
  notifications_enabled: boolean;
  maintenance_mode: boolean;
  reason: string;
}>;

export function getAdminSettings(accessToken: string) {
  return apiFetch<AdminPlatformSettings>("/api/v1/admin/settings", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateAdminSettings(accessToken: string, payload: AdminPlatformSettingsUpdate) {
  return apiFetch<AdminPlatformSettings>("/api/v1/admin/settings", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

// Phase 17's commission config — GET/PATCH already existed backend-side
// with no frontend built yet ("Rules must be explicit" — see admin.py).
// Settings.tsx is the first UI to surface the platform default rate.
export type AdminCommissionType = "PERCENTAGE" | "FIXED";

export type AdminCommissionRule = {
  restaurant_id: string | null;
  restaurant_name: string | null;
  commission_type: AdminCommissionType;
  value: string;
  updated_at: string;
};

export type AdminCommissionConfig = {
  default: AdminCommissionRule | null;
  restaurant_overrides: AdminCommissionRule[];
};

export function getAdminCommissionConfig(accessToken: string) {
  return apiFetch<AdminCommissionConfig>("/api/v1/admin/commissions", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function setAdminDefaultCommission(accessToken: string, commissionType: AdminCommissionType, value: string) {
  return apiFetch<AdminCommissionConfig>("/api/v1/admin/commissions", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ default: { commission_type: commissionType, value } }),
  });
}
