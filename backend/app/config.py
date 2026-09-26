from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    secret_key: str = "development-only-secret-key-replace-before-deploying"

    database_url: str = "sqlite+aiosqlite:///./fihy.db"
    # Runs `alembic upgrade head` at startup, which keeps a checkout
    # working with no extra step. Turn it off wherever more than one worker
    # can boot at once and make the upgrade a deploy step instead.
    auto_migrate: bool = True

    # The mobile client holds one long-lived access token and has no refresh
    # interceptor, so the default outlives a session by a wide margin. A
    # refresh token is still issued and /auth/token/refresh accepts it, which
    # lets the client opt into short-lived tokens without a contract change.
    access_token_ttl_seconds: int = 60 * 60 * 24 * 30
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 90

    public_base_url: str = "http://127.0.0.1:8000"

    # Used only when R2 credentials are absent: images land on disk and are
    # served from /media with the same short-lived signed-URL semantics, so
    # local development exercises the real client code path.
    media_root: str = "./var/media"

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "fihy"
    r2_endpoint_url: str = ""
    signed_url_ttl_seconds: int = 600

    # Reports are accepted inside this box only. Widened from the prototype's
    # Mumbai box to all of India; set geofence_enabled=false to drop it.
    geofence_enabled: bool = True
    geofence_min_latitude: float = 6.0
    geofence_max_latitude: float = 37.6
    geofence_min_longitude: float = 68.0
    geofence_max_longitude: float = 97.5

    default_radius_m: float = 500.0
    # A new report within this of an existing one, in the same category, is
    # probably the same thing; the report screen offers to join it instead.
    duplicate_radius_m: float = 100.0
    # A support carrying photos has to be sent from within this of the report:
    # the duplicate radius plus room for two phones' GPS error.
    support_radius_m: float = 150.0
    max_radius_m: float = 50_000.0
    default_limit: int = 20
    max_limit: int = 100

    max_photos_per_report: int = 5
    max_photo_bytes: int = 12 * 1024 * 1024
    thumbnail_width: int = 800
    stored_image_width: int = 1920
    jpeg_quality: int = 82

    # A report is confirmed once this many people other than the reporter have
    # supported it *with a photo*. Two, because one other person with a camera
    # is corroboration and the reporter alone is not.
    photo_supports_to_confirm: int = 2
    # How long after confirmation the report is handed back to the people who
    # filed it, if nothing else has moved.
    contributions_after_days: int = 5
    # Any more than this and the poll stops being a decision.
    max_fix_dates_per_issue: int = 5

    # Named on every letter until ward boundaries can say which body actually
    # owns a given location.
    default_authority: str = "the municipal corporation"
    # Where the app is served from. "*" is fine while the only client is a
    # native app carrying a bearer token; narrow it before there is a web one.
    cors_origins: str = "*"
    # The interactive docs describe every endpoint and every field. Off outside
    # development unless deliberately turned back on.
    public_docs: bool = False
    # A confirmed report waits this long before being raised, so the community
    # has a chance to add to it first.
    escalate_after_hours: int = 24
    # How many reports one cron run will raise. Keeps a backlog from turning
    # into a burst of letters.
    escalate_batch_size: int = 25
    check_batch_size: int = 100

    # Letters go out from fihy's own domain carrying the reporter's name. They
    # cannot go out *as* the reporter: a message with their address in From,
    # sent from this server, fails DMARC and is rejected.
    mail_from_domain: str = ""
    mail_from_name: str = "fihy"
    # Where replies land. Usually a subdomain pointed at the mail provider.
    mail_reply_domain: str = ""
    # Where letters are addressed until ward boundaries can say who owns a
    # location. With this empty, nothing is sent.
    authority_email: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # Shared secret the mail provider signs its webhook posts with.
    inbound_mail_secret: str = ""
    # How far a signed post's timestamp may be from now. Outside it the post
    # is refused, so a captured one cannot be replayed later.
    webhook_tolerance_seconds: int = 300
    # Evidence carried on the letter itself. More than a few and it bounces on
    # size at the receiving end.
    max_letter_attachments: int = 3

    # Plain-language summaries of an issue and its replies. With no key the
    # summarizer is a no-op and ai_summary stays null.
    anthropic_api_key: str = ""
    ai_summary_model: str = "claude-opus-5"
    # A summary is rewritten at most this often, however many people reply.
    ai_summary_min_interval_seconds: int = 300

    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_requests_per_phone_per_hour: int = 5
    otp_requests_per_ip_per_hour: int = 20
    # The one header the edge proxy writes the caller's address into:
    # fly-client-ip on Fly, cf-connecting-ip behind Cloudflare. Blank uses the
    # connecting address. Nothing else is read, since the caller controls it.
    client_ip_header: str = ""
    # Writes are capped per account per hour too. Somebody signed in can still
    # flood the feed, and only OTP was ever limited.
    reports_per_user_per_hour: int = 10
    supports_per_user_per_hour: int = 60
    # Rows older than this are pruned. Both tables hold verified phone numbers,
    # and nothing reads them after the challenge is spent or the hour is up.
    otp_retention_hours: int = 72
    # When set, this code is accepted for any phone and no SMS is sent. Leave
    # empty in anything user-facing.
    otp_debug_code: str = Field(default="")

    @property
    def resolved_r2_endpoint(self) -> str:
        if self.r2_endpoint_url:
            return self.r2_endpoint_url
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return ""

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_local(self) -> bool:
        """Environments that are meant to be thrown away. Everything else is
        treated as somewhere data has to survive a redeploy."""
        return self.environment in {"development", "test"}

    @property
    def mail_configured(self) -> bool:
        return bool(
            self.smtp_host
            and self.mail_from_domain
            and self.mail_reply_domain
            and self.authority_email
        )

    @property
    def ai_summary_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def storage_configured(self) -> bool:
        return bool(
            self.resolved_r2_endpoint
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
