import { apiFetch } from "@/services/api/apiClient";

export const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export type OperatingHourRead = {
  day_of_week: number;
  day_name: string;
  is_closed: boolean;
  open_time: string | null;
  close_time: string | null;
};

export type OperatingHourEntry = {
  day_of_week: number;
  is_closed: boolean;
  open_time: string | null;
  close_time: string | null;
};

export type RestaurantHours = {
  restaurant_id: string;
  hours: OperatingHourRead[];
};

export function getRestaurantHours(accessToken: string) {
  return apiFetch<RestaurantHours>("/api/v1/restaurant/hours", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateRestaurantHours(accessToken: string, hours: OperatingHourEntry[]) {
  return apiFetch<RestaurantHours>("/api/v1/restaurant/hours", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ hours }),
  });
}

export function emptyWeek(): OperatingHourEntry[] {
  return DAY_NAMES.map((_, index) => ({
    day_of_week: index,
    is_closed: false,
    open_time: "10:00:00",
    close_time: "22:00:00",
  }));
}
