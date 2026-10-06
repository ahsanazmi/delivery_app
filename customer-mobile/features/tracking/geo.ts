// Live Rider Tracking Phase 17/18 — a small shared home for the plain
// straight-line distance calculation both track/[id].tsx (the "X km away"
// readout) and RiderMap.tsx (deciding whether a new rider position is
// normal movement or a large jump) need, so it exists in exactly one
// place client-side rather than being copied a second time.
const EARTH_RADIUS_KM = 6371;

export function distanceKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return EARTH_RADIUS_KM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
