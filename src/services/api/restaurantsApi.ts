import { apiFetch } from './apiClient';
import type { Restaurant } from '@/types/restaurant';

export type { Restaurant } from '@/types/restaurant';

export function getRestaurants() {
  return apiFetch<Restaurant[]>('/api/v1/restaurants?open_only=true');
}

export function getRestaurant(id: string) {
  return apiFetch<Restaurant>(`/api/v1/restaurants/${id}`);
}
