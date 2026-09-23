export type ProductCardData = {
  id: string;
  name: string;
  price: number;
  imageUrl?: string | null;
  isVeg: boolean;
  isAvailable: boolean;
};

export type MenuCategory = {
  id: string;
  restaurant_id: string;
  name: string;
  display_order: number;
};

export type Product = {
  id: string;
  restaurant_id: string;
  category_id: string | null;
  name: string;
  description: string | null;
  image_url: string | null;
  price: string | number;
  is_available: boolean;
};
