import { apiFetch } from './apiClient';
import type { Category } from '@/types/restaurant';
import type { Restaurant } from '@/types/restaurant';
import type { Product } from '@/types/product';

export type SearchResponse = {
  restaurants: Restaurant[];
  products: Product[];
  categories: Category[];
  page: number;
  limit: number;
};

export function searchCustomer(params: { q?: string; categoryId?: string; page?: number; limit?: number }) {
  const query = new URLSearchParams();
  if (params.q) query.set('q', params.q);
  if (params.categoryId) query.set('category_id', params.categoryId);
  if (params.page) query.set('page', String(params.page));
  if (params.limit) query.set('limit', String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiFetch<SearchResponse>(`/api/v1/customer/search${suffix}`);
}
