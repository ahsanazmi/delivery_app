export type Restaurant = {
  id: string;
  category_id: string | null;
  name: string;
  description: string | null;
  address: string;
  logo_url: string | null;
  cover_image_url: string | null;
  rating: string | number;
  delivery_time_minutes: number;
  minimum_order: string | number;
  delivery_fee: string | number;
  is_open: boolean;
};

export type Category = {
  id: string;
  name: string;
  image_url: string | null;
  display_order: number;
  created_at: string;
};
