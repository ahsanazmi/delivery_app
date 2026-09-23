import { apiFetch } from './apiClient';
import type { MenuCategory, Product } from '@/types/product';

export function getRestaurantMenuCategories(restaurantId: string) {
  return apiFetch<MenuCategory[]>(`/api/v1/customer/restaurants/${restaurantId}/categories`);
}

export function getRestaurantProducts(restaurantId: string, categoryId?: string) {
  const suffix = categoryId ? `?category_id=${categoryId}` : '';
  return apiFetch<Product[]>(`/api/v1/customer/restaurants/${restaurantId}/products${suffix}`);
}

export function getProduct(id: string) {
  return apiFetch<Product>(`/api/v1/customer/products/${id}`);
}
