from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Both the in-code default and the literal placeholder shipped in .env.example
# — either one landing in a real deployment would mean every JWT in the
# system is signed with a secret that's public in this repository's history.
_INSECURE_JWT_SECRETS = {
    "change-me-before-production-use-please",
    "replace-with-a-long-random-secret-at-least-32-characters",
}


class Settings(BaseSettings):
    PROJECT_NAME: str = "Say Hi Chai API"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    # Final System Validation (Phase 31) — FastAPI's own `debug` constructor
    # arg already defaulted to False everywhere in this app (never passed
    # explicitly before), which is why no debug-mode leak was ever observed
    # — but an implicit default isn't something a deployment can point to
    # and verify. Made explicit and settable here so "DEBUG=false in
    # production" is a real, auditable configuration value, and guarded the
    # same way JWT_SECRET_KEY already is: a production environment can
    # never actually boot with it left on.
    DEBUG: bool = False
    # Logging & Error Handling (Phase 26) — server-side only, never sent to
    # a client. WARNING is the default so routine INFO-level noise doesn't
    # drown out the failure/conflict/exception events this level is meant
    # to surface; set to INFO in an environment that wants admin-action
    # visibility in the log stream too (the DB-backed AdminAuditLog remains
    # the authoritative, queryable record of admin actions regardless).
    LOG_LEVEL: str = "WARNING"
    DATABASE_URL: str = "postgresql+psycopg://say_hi_chai:say_hi_chai@localhost:5433/say_hi_chai"
    JWT_SECRET_KEY: str = "change-me-before-production-use-please"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    # Push Notification Service (Phase 17) — optional. Expo's push API
    # works with no credential at all (the default, unset); setting this
    # only raises Expo's own rate limits and ties usage to this project's
    # Expo account (https://docs.expo.dev/push-notifications/sending-
    # notifications/#additional-security). Never required for local dev.
    EXPO_ACCESS_TOKEN: str = ""
    # Maps & Location System Phase 9/8 — Forward Geocoding / Address
    # Search and Reverse Geocoding. Photon (komoot's open-source OSM
    # geocoder) rather than Google Places/Geocoding — no API key at all,
    # so unlike every other provider setting above this one is never
    # "blank means disabled"; blank here means "use komoot's free public
    # instance" (their own documented 1 request/second fair-use limit —
    # see location_search.py's own module-level throttle, shared by both
    # forward and reverse calls since they hit the same instance).
    # This is the *root* URL — Photon's own forward-search endpoint
    # lives under it at /api/, while reverse geocoding is a sibling path
    # at /reverse, not nested under /api/ at all (confirmed against the
    # real public instance; not guessed), so location_search.py builds
    # each full path from this same root rather than one being derived
    # from the other. Point this at a self-hosted Photon instance, or a
    # different Nominatim-compatible provider's root URL, to swap
    # providers without any code change.
    PHOTON_API_BASE_URL: str = "https://photon.komoot.io"
    # Maps & Location System Phase 17 — Routes Foundation. Free/open-source
    # routing (OSRM — Open Source Routing Machine), not Google Routes API,
    # for the same reason Photon was chosen over Google Places: no paid
    # key, consistent with every other location decision on this platform.
    # This is project-osrm.org's own public demo server — no API key
    # needed, but it documents a 1 request/second limit (see routing.py's
    # own throttle) and its usage policy restricts it to non-commercial
    # use; a production deployment of this platform should point this at
    # a self-hosted OSRM instance instead (a regional OSM extract, not the
    # whole planet, keeps this practical to run). Swappable via this one
    # setting, same pattern as PHOTON_API_BASE_URL above.
    OSRM_API_BASE_URL: str = "https://router.project-osrm.org"
    # Comma-separated list of browser origins allowed to call this API (the two
    # Vite web apps, both hostname spellings since browsers treat localhost and
    # 127.0.0.1 as different origins). 5180 is included because admin-web's
    # dev server falls back to it whenever 5173-5175 are already taken by
    # other apps on the same machine. Native mobile apps (customer-mobile,
    # rider-mobile) aren't subject to browser CORS, so they don't need an entry.
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:5180,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5180"
    )

    # Live Rider Tracking Phase 7 — Location Update Throttling. Previously
    # hardcoded in app/services/rider_location.py; moved here so every
    # tunable governing how often/how-much a rider's GPS updates are
    # accepted lives in one configurable place, not scattered as magic
    # numbers through the application.
    RIDER_LOCATION_MIN_INTERVAL_SECONDS: int = 10
    # A new history row is written once EITHER this much time OR this much
    # straight-line movement (in meters) has happened since the last stored
    # point, whichever comes first — the same "time OR distance" pattern
    # rider-mobile's own background-location task already uses. The
    # fast-path "current position" cache on User always updates regardless
    # of either threshold; only the durable history ledger is throttled.
    RIDER_LOCATION_MIN_MOVEMENT_METERS: float = 15.0
    # A reported accuracy worse (larger) than this, in meters, is treated as
    # unreliable *only* in combination with an implausible implied-speed
    # jump (see RIDER_LOCATION_MAX_PLAUSIBLE_SPEED_MPS) — Live Rider
    # Tracking Phase 8's own instruction is to "keep filtering
    # conservative," so poor accuracy alone, from an otherwise normal
    # point, is never rejected on its own.
    RIDER_LOCATION_MAX_ACCEPTED_ACCURACY_METERS: float = 100.0
    # ~200 km/h — well above any real delivery vehicle, deliberately loose
    # so ordinary traffic/highway movement is never mistaken for an
    # impossible GPS jump. Combined with the accuracy threshold above (both
    # conditions must hold) before a point is rejected.
    RIDER_LOCATION_MAX_PLAUSIBLE_SPEED_MPS: float = 55.0
    # A client-reported location captured_at further in the past or future
    # than these bounds is treated as an invalid timestamp and the whole
    # update is rejected — a device clock can be wrong, but not wrong by
    # this much without something being genuinely broken.
    RIDER_LOCATION_MAX_TIMESTAMP_AGE_SECONDS: int = 3600
    RIDER_LOCATION_MAX_TIMESTAMP_FUTURE_SECONDS: int = 60
    # Live Rider Tracking Phase 5/19 — thresholds for the LIVE/STALE/OFFLINE
    # state a rider's last-known position is classified into, documented in
    # docs/live-tracking-architecture.md §5.
    RIDER_LOCATION_STALE_AFTER_SECONDS: int = 30
    RIDER_LOCATION_OFFLINE_AFTER_SECONDS: int = 120
    # Live Rider Tracking Phase 22/24 — Live ETA refresh strategy. A live
    # ETA is only recalculated (a real OSRM call) once the rider has moved
    # this far, OR this much time has passed, since the last calculation
    # for that order — never on every single GPS ping. See
    # docs/live-tracking-architecture.md §10.
    LIVE_ETA_MIN_REFRESH_SECONDS: int = 60
    LIVE_ETA_MIN_MOVEMENT_METERS: float = 300.0
    # Live Rider Tracking Phase 34 — Notification Integration. "Rider is
    # approaching" fires once a rider on the OUT_FOR_DELIVERY leg comes
    # within this straight-line distance of the delivery address — a
    # customer-facing heads-up, not a precision ETA (that's live_eta's
    # job), so the simple/cheap distance_km estimate is intentional here
    # rather than a route-based (OSRM) distance.
    RIDER_APPROACHING_DISTANCE_KM: float = 0.5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def model_post_init(self, __context: object) -> None:
        if self.ENVIRONMENT == "production" and (
            self.JWT_SECRET_KEY in _INSECURE_JWT_SECRETS or len(self.JWT_SECRET_KEY) < 32
        ):
            raise RuntimeError(
                "JWT_SECRET_KEY is missing, a placeholder, or too short for a production "
                "deployment. Generate a real one first, e.g.: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if self.ENVIRONMENT == "production" and self.DEBUG:
            raise RuntimeError("DEBUG must be false in a production deployment (ENVIRONMENT=production).")
        # Production Payment Readiness (Phase 40) — same fail-fast-at-boot
        # philosophy as the two guards above, applied to Razorpay. Razorpay's
        # own documented convention prefixes every Key ID with either
        # rzp_test_ or rzp_live_ — a real, reliable signal, not a guess.
        # Never let a production deployment silently take real customer
        # payments against Razorpay's *test* mode (money would appear to
        # move but never actually settle) just because someone forgot to
        # swap the .env file when promoting to production.
        if self.ENVIRONMENT == "production" and self.RAZORPAY_KEY_ID.startswith("rzp_test_"):
            raise RuntimeError(
                "RAZORPAY_KEY_ID is a Razorpay TEST-mode key (rzp_test_...) in a production "
                "deployment (ENVIRONMENT=production). Use a live key (rzp_live_...) instead."
            )
        # A half-configured state is more dangerous than an unconfigured
        # one: with RAZORPAY_KEY_ID set, online payments are already being
        # accepted (create_payment_for_order's own provider check would
        # otherwise 503 an online payment attempt, so a missing key id here
        # is self-evidently caught already) — but a genuinely captured
        # payment can then only ever be confirmed asynchronously via a
        # signed webhook. Without RAZORPAY_WEBHOOK_SECRET, every such
        # webhook is unverifiable and rejected at the signature check, so a
        # real payment could be captured at Razorpay and never resolve past
        # PENDING/PROCESSING in this backend at all.
        if self.ENVIRONMENT == "production" and self.RAZORPAY_KEY_ID and not self.RAZORPAY_WEBHOOK_SECRET:
            raise RuntimeError(
                "RAZORPAY_KEY_ID is set (online payments would be accepted) but "
                "RAZORPAY_WEBHOOK_SECRET is empty — captured payments could never be confirmed. "
                "Configure RAZORPAY_WEBHOOK_SECRET before enabling online payments in production."
            )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
