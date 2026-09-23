import { apiFetch } from './apiClient';
import type { Restaurant } from '@/types/restaurant';

export type { Restaurant } from '@/types/restaurant';

export type GetRestaurantsParams = {
  categoryId?: string;
  q?: string;
  openOnly?: boolean;
  offset?: number;
  limit?: number;
};

export function getRestaurants(params?: GetRestaurantsParams) {
  const query = new URLSearchParams();
  if (params?.categoryId) query.set('category_id', params.categoryId);
  if (params?.q) query.set('q', params.q);
  if (params?.openOnly) query.set('open_only', 'true');
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiFetch<Restaurant[]>(`/api/v1/customer/restaurants${suffix}`);
}

export function getRestaurant(id: string) {
  return apiFetch<Restaurant>(`/api/v1/customer/restaurants/${id}`);
}
