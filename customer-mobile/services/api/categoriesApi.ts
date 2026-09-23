import { apiFetch } from './apiClient';
import type { Category } from '@/types/restaurant';

export type { Category } from '@/types/restaurant';

export function getCategories() {
  return apiFetch<Category[]>('/api/v1/customer/categories');
}

export function getCategory(id: string) {
  return apiFetch<Category>(`/api/v1/customer/categories/${id}`);
}
