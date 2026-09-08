export type Restaurant = {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  phone: string;
  address: string;
  latitude: string | number;
  longitude: string | number;
  logo_url: string | null;
  cover_image_url: string | null;
  minimum_order: string | number;
  delivery_fee: string | number;
  average_rating: string | number;
  is_open: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
