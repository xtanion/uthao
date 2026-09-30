from datetime import date, datetime, time, timezone

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .enums import ActivityType, Category, EscalationState, Severity, Status

PHONE_PATTERN = r"^\+[1-9]\d{7,14}$"


def rfc3339(value: datetime) -> str:
    """SQLite hands back naive datetimes; everything stored is UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class ReporterOut(BaseModel):
    """Who filed an issue, so a card can credit them and link to a profile."""

    id: str
    display_name: str


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    category: Category
    severity: Severity
    status: Status
    latitude: float
    longitude: float
    locality: str | None
    confirmation_count: int
    confirmed_by_me: bool
    comment_count: int
    photo_count: int
    # Supports from somebody other than the reporter that carried a photo.
    # Reaching photo_supports_to_confirm is what confirms a report.
    photo_support_count: int
    # How many more photo-backed supports would confirm this, so the app can
    # say "one more photo confirms this" without re-implementing the rule.
    photo_supports_needed: int
    confirmed_at: datetime | None = None
    # confirmed_at plus the contributions window. Null until confirmed.
    contributions_open_at: datetime | None = None
    cover_url: str | None
    # The whole gallery, on the detail read only. The feed serializes many
    # issues at once and needs one signed link each, not all of them.
    photos: list["PhotoOut"] | None = None
    ai_summary: str | None = None
    reporter: ReporterOut
    created_at: datetime

    @field_serializer("created_at")
    def _created_at(self, value: datetime) -> str:
        return rfc3339(value)

    @field_serializer("confirmed_at", "contributions_open_at")
    def _moment(self, value: datetime | None) -> str | None:
        return rfc3339(value) if value else None


class PhotoOut(BaseModel):
    """One image in the gallery, credited to whoever took it."""

    id: str
    url: str
    thumbnail_url: str
    contributor: ReporterOut
    # True for photos that came with the original report.
    from_report: bool
    created_at: datetime

    @field_serializer("created_at")
    def _created_at(self, value: datetime) -> str:
        return rfc3339(value)


class Page(BaseModel):
    items: list[IssueOut]
    next_cursor: str | None = None


class FeedPage(Page):
    """The home feed, plus how far it had to reach to fill itself."""

    # Null means the ladder was exhausted and distance stopped being a filter
    # at all, so these came from wherever anybody has reported anything.
    radius_m: float | None
    # True when nothing was close enough and the ring was widened, so the app
    # can say so rather than quietly showing somewhere else's problems.
    widened: bool


class DuplicateOut(BaseModel):
    """A report close enough that a new one is probably the same thing."""

    issue: IssueOut
    distance_m: float


class DuplicatesOut(BaseModel):
    items: list[DuplicateOut]
    radius_m: float


class SupportOut(BaseModel):
    """One person's backing: optional words, optional photos, always a person."""

    id: str
    body: str | None
    photos: list[PhotoOut]
    author: ReporterOut
    # Marks the reporter's own follow-ups, so a thread reads as a conversation
    # with the person who filed it rather than a row of anonymous voices.
    author_is_reporter: bool
    mine: bool
    created_at: datetime

    @field_serializer("created_at")
    def _created_at(self, value: datetime) -> str:
        return rfc3339(value)


class SupportPage(BaseModel):
    items: list[SupportOut]
    next_cursor: str | None = None
    total: int


class FixDateIn(BaseModel):
    fix_on: date
    # Optional so a day can still be offered before the hour is settled.
    fix_time: time | None = None


class FixDateOut(BaseModel):
    id: str
    fix_on: date
    fix_time: time | None
    vote_count: int
    # Who has said they will be there, newest first. Capped: the count is the
    # truth, this is only enough to show faces and fill a list.
    going: list[ReporterOut]
    # Whether the reader has said they will be there that day.
    voted_by_me: bool
    proposed_by: ReporterOut
    mine: bool

    @field_serializer("fix_on")
    def _fix_on(self, value: date) -> str:
        return value.isoformat()

    @field_serializer("fix_time")
    def _fix_time(self, value: time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class FixDatesOut(BaseModel):
    items: list[FixDateOut]
    # False before the window opens; the poll is readable but closed.
    open: bool
    opens_at: datetime | None
    # True once the reader has used their one proposal on this report.
    proposed_by_me: bool
    remaining_slots: int

    @field_serializer("opens_at")
    def _opens_at(self, value: datetime | None) -> str | None:
        return rfc3339(value) if value else None


class OtpRequestIn(BaseModel):
    phone: str = Field(pattern=PHONE_PATTERN)


class OtpVerifyIn(BaseModel):
    phone: str = Field(pattern=PHONE_PATTERN)
    code: str = Field(min_length=4, max_length=8)


class FirebaseSignInIn(BaseModel):
    # The ID token the app gets back from Firebase after the phone is verified.
    id_token: str = Field(min_length=16, max_length=8192)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str


class MeOut(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None = None


class MeIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=40)


class EscalationOut(BaseModel):
    """The letter raised on the residents' behalf, as they may read it.

    Deliberately without `recipient` or `reply_token`: one is an official's
    address and the other is the correlation secret replies come back on.
    """

    authority: str
    state: EscalationState
    subject: str
    body: str
    reference: str | None
    detail: str | None
    sent_at: datetime | None

    @field_serializer("sent_at")
    def _sent_at(self, value: datetime | None) -> str | None:
        return rfc3339(value) if value else None


class IssueSummary(BaseModel):
    """Just enough of an issue to render a notification row."""

    id: str
    title: str
    category: Category
    severity: Severity
    status: Status
    cover_url: str | None
    confirmation_count: int


class NotificationOut(BaseModel):
    id: str
    type: ActivityType
    read: bool
    actor_name: str | None
    from_status: Status | None
    to_status: Status | None
    issue: IssueSummary
    created_at: datetime

    @field_serializer("created_at")
    def _created_at(self, value: datetime) -> str:
        return rfc3339(value)


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None = None
    unread_count: int


class MarkReadIn(BaseModel):
    # Omit ids to mark the whole feed read, which is what the screen does when
    # it opens.
    ids: list[str] | None = None


class UnreadCountOut(BaseModel):
    unread_count: int


class ContributionsOut(BaseModel):
    """The tallies behind the reputation score, each one separately legible."""

    posts: int
    upvotes_received: int
    supports_given: int
    comments_written: int
    resolutions: int


class ProfileOut(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None
    reputation: int
    contributions: ContributionsOut
    joined_at: datetime

    @field_serializer("joined_at")
    def _joined_at(self, value: datetime) -> str:
        return rfc3339(value)


class StatsTotals(BaseModel):
    reported: int
    confirmed: int
    raised: int
    resolved: int
    photos: int
    contributors: int
    emails_sent: int


class StatsWeek(BaseModel):
    week_start: date
    reported: int
    resolved: int


class StatsCategory(BaseModel):
    category: Category
    total: int
    resolved: int


class StatsPoint(BaseModel):
    latitude: float
    longitude: float
    resolved: bool


class StatsArea(BaseModel):
    slug: str
    city: str
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float


class StatsAreaOption(BaseModel):
    slug: str
    city: str
    reports: int


class StatsContributor(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None
    reputation: int
    reports: int
    resolutions: int


class StatsOut(BaseModel):
    area: StatsArea | None
    totals: StatsTotals
    weeks: list[StatsWeek]
    categories: list[StatsCategory]
    points: list[StatsPoint]
    generated_at: datetime

    @field_serializer("generated_at")
    def _generated_at(self, value: datetime) -> str:
        return rfc3339(value)


class StatsContributorsOut(BaseModel):
    period: str
    since: datetime
    area: StatsArea | None
    items: list[StatsContributor]

    @field_serializer("since")
    def _since(self, value: datetime) -> str:
        return rfc3339(value)
