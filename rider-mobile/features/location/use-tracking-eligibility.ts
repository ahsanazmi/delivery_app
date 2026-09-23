import { useEffect } from "react";

import { useRiderStore } from "@/store/riderStore";

// Much coarser than the 12s location-report interval — this only refreshes
// the two signals ("is this rider online" / "do they have an active
// delivery") that decide WHETHER to report at all, not the position itself.
// This hook is mounted once, globally, in (rider)/_layout.tsx, so it polls
// the full dashboard endpoint (6 backend queries) for the entire time the
// app is open on ANY screen — not just while looking at the dashboard
// itself. Phase 30: raised from 30s to 60s specifically for that reason —
// eligibility changes (going online/offline, a delivery starting/ending)
// don't need sub-minute reaction time, and every screen that actually
// causes one of those changes already refreshes riderStore.dashboard
// itself via its own success handler, so this interval is purely the
// "catch anything else" backstop, not the primary way eligibility updates.
const ELIGIBILITY_POLL_INTERVAL_MS = 60000;

/**
 * Phase 22's transmission rule, as a single boolean: "RIDER = ONLINE, or
 * RIDER has an active delivery." Polls GET /rider/dashboard — one endpoint
 * already returns both is_online and current_assignment — rather than
 * combining two separate stores/requests.
 */
export function useTrackingEligibility(accessToken: string | null): boolean {
  const dashboard = useRiderStore((state) => state.dashboard);
  const fetchDashboard = useRiderStore((state) => state.fetchDashboard);

  useEffect(() => {
    if (!accessToken) return;

    void fetchDashboard(accessToken);
    const interval = setInterval(() => void fetchDashboard(accessToken), ELIGIBILITY_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [accessToken, fetchDashboard]);

  return Boolean(dashboard?.is_online || dashboard?.current_assignment);
}
