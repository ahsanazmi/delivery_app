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
