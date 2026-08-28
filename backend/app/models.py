import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import (
    ActivityType,
    Category,
    EscalationState,
    MessageDirection,
    Severity,
    Status,
)


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(python_enum: type) -> Enum:
    return Enum(
        python_enum,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
        length=32,
    )


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # Nullable only so a closed account can give the number back: deleting it
    # is the point, and a tombstone string would have to be unique, would not
    # fit in a phone-sized column, and would still be a number-shaped thing
    # sitting where a number used to be. Live accounts always have one.
    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, index=True, default=None
    )
    display_name: Mapped[str] = mapped_column(String(80))
    avatar_key: Mapped[str | None] = mapped_column(String(400), default=None)
    # Set when the person closed their account. The row survives so the reports
    # other people corroborated do not lose their evidence, but everything on it
    # that identifies anybody is gone by then.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "client_report_id", name="uq_issues_reporter_client_report"
        ),
        Index("ix_issues_lat_lng", "latitude", "longitude"),
        Index("ix_issues_reporter_created", "reporter_id", "created_at"),
        # The escalate job asks for community_verified reports confirmed before
        # a cutoff, oldest first. Without this it reads every issue there is.
        Index("ix_issues_status_confirmed", "status", "confirmed_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    reporter_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE")
    )
    client_report_id: Mapped[str] = mapped_column(String(64))

    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[Category] = mapped_column(_enum(Category))
    severity: Mapped[Severity] = mapped_column(_enum(Severity))
    status: Mapped[Status] = mapped_column(_enum(Status), default=Status.REPORTED)

    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    locality: Mapped[str | None] = mapped_column(String(120), default=None)

    # confirmation_count is how many people backed this; comment_count is how
    # many of those wrote something. Both are counts of supports.
    confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    # Supports from somebody other than the reporter that carried a photo. This
    # is what confirms a report: a second person standing in the same place with
    # a camera is evidence in a way that a tap is not.
    photo_support_count: Mapped[int] = mapped_column(Integer, default=0)
    # When the report crossed that bar. The contributions clock counts from
    # here, so it is a stored moment rather than something derived after the
    # fact - withdrawals can move it, and a derived one could not tell you when.
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    ai_summary: Mapped[str | None] = mapped_column(Text, default=None)
    ai_summary_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # How many replies the current summary was written from. Lets the rewrite
    # rule tell "nothing new to say" from "has not caught up yet".
    ai_summary_voices: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    reporter: Mapped["User"] = relationship(lazy="selectin")

    photos: Mapped[list["IssuePhoto"]] = relationship(
        back_populates="issue",
        cascade="all, delete-orphan",
        order_by="IssuePhoto.position",
        lazy="selectin",
    )


class IssuePhoto(Base):
    __tablename__ = "issue_photos"
    __table_args__ = (
        Index("ix_issue_photos_issue_created", "issue_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE")
    )
    # Every photo names the person who took it, whether it arrived with the
    # original report or with a later support. That is what lets the gallery
    # credit each image.
    contributor_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Null for the reporter's own photos, which belong to the issue itself.
    # Set for photos that arrived attached to somebody's support, so removing
    # the support takes its photos with it.
    support_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("supports.id", ondelete="CASCADE"), default=None,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    original_key: Mapped[str] = mapped_column(String(400))
    thumbnail_key: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    issue: Mapped[Issue] = relationship(back_populates="photos")
    contributor: Mapped[User] = relationship(lazy="selectin")


class Support(Base):
    """One person backing one issue: I saw this too, optionally with words and
    photos.

    This is deliberately a single row rather than a confirmation plus a comment
    plus an upload. Someone standing in front of a broken thing does one act,
    and splitting it into three made a person who had photographed the problem
    indistinguishable from one who tapped a button. `body` and photos are both
    optional, so a bare support is still just a +1.
    """

    __tablename__ = "supports"
    __table_args__ = (
        UniqueConstraint("issue_id", "user_id", name="uq_supports_issue_user"),
        Index("ix_supports_issue_created", "issue_id", "created_at"),
        Index("ix_supports_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE")
    )
    body: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(lazy="selectin")
    photos: Mapped[list["IssuePhoto"]] = relationship(
        cascade="all, delete-orphan",
        order_by="IssuePhoto.position",
        lazy="selectin",
    )


class FixDate(Base):
    """A day somebody is offering to go and fix the thing.

    One per person per issue: proposing a date is a commitment, and a person
    can only be in one place on one day. Voting is separate and unlimited,
    because agreeing to turn up on a day somebody else picked costs nothing to
    say and is the whole point of the poll.
    """

    __tablename__ = "fix_dates"
    __table_args__ = (
        UniqueConstraint("issue_id", "created_by", name="uq_fix_dates_issue_creator"),
        UniqueConstraint("issue_id", "fix_on", name="uq_fix_dates_issue_day"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE")
    )
    created_by: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    fix_on: Mapped[date] = mapped_column(Date)
    # The hour belongs to the day, not to each person: whoever puts a day up
    # sets when, and agreeing to the day is agreeing to the time. Nullable so
    # days proposed before this existed still read.
    fix_time: Mapped[time | None] = mapped_column(Time, default=None)
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    creator: Mapped[User] = relationship(lazy="selectin")
    votes: Mapped[list["FixDateVote"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class FixDateVote(Base):
    __tablename__ = "fix_date_votes"
    __table_args__ = (
        UniqueConstraint("fix_date_id", "user_id", name="uq_fix_date_votes_date_user"),
        Index("ix_fix_date_votes_user_issue", "user_id", "issue_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    fix_date_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("fix_dates.id", ondelete="CASCADE")
    )
    # Denormalized so "which days did this person say yes to on this report"
    # is one index hit rather than a join back through fix_dates.
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    # Loaded with the vote so a poll row can name who is going without a
    # second query per day.
    voter: Mapped[User] = relationship(lazy="selectin")


class Escalation(Base):
    """A report raised with the body responsible for it.

    One per issue: raising the same pothole twice is noise to whoever receives
    it, and the unique constraint is also what stops two overlapping cron runs
    from both sending. The draft is kept whether or not it went out, because a
    letter sent on a resident's behalf should be readable by them afterwards.
    """

    __tablename__ = "escalations"
    __table_args__ = (
        UniqueConstraint("issue_id", name="uq_escalations_issue"),
        Index("uq_escalations_reply_token", "reply_token", unique=True),
        # The check job walks sent escalations least-recently-checked first.
        Index("ix_escalations_state_checked", "state", "checked_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE")
    )
    authority: Mapped[str] = mapped_column(String(160))
    recipient: Mapped[str | None] = mapped_column(String(320), default=None)
    # The local part of the address replies come back to. Random and unique, so
    # an address is the correlation key even when a mail client mangles the
    # subject or drops the threading headers.
    reply_token: Mapped[str | None] = mapped_column(String(40), default=None)
    message_id: Mapped[str | None] = mapped_column(String(300), default=None)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[EscalationState] = mapped_column(
        _enum(EscalationState), default=EscalationState.DRAFTED
    )
    # Whatever the channel calls it: a ticket number, a message id, a URL.
    reference: Mapped[str | None] = mapped_column(String(200), default=None)
    # Why it failed, or what the last status check said.
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    bounced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    issue: Mapped[Issue] = relationship(lazy="selectin")
    messages: Mapped[list["EscalationMessage"]] = relationship(
        cascade="all, delete-orphan",
        order_by="EscalationMessage.created_at",
        lazy="selectin",
    )


class EscalationMessage(Base):
    """One email on the thread, in either direction.

    Kept so the person who reported the problem can read what was sent on their
    behalf and what came back. A complaint made for somebody that they cannot
    afterwards read is not much of a complaint.
    """

    __tablename__ = "escalation_messages"
    __table_args__ = (
        Index("ix_escalation_messages_thread", "escalation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    escalation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("escalations.id", ondelete="CASCADE")
    )
    direction: Mapped[MessageDirection] = mapped_column(_enum(MessageDirection))
    sender: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(300), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ActivityEvent(Base):
    """One line in a reporter's notifications feed.

    Written when something happens to an issue they reported. The recipient is
    always the reporter; an actor is whoever caused it, and is null for changes
    the system made on its own.
    """

    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE")
    )
    issue_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("issues.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    type: Mapped[ActivityType] = mapped_column(_enum(ActivityType))
    from_status: Mapped[Status | None] = mapped_column(_enum(Status), default=None)
    to_status: Mapped[Status | None] = mapped_column(_enum(Status), default=None)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    issue: Mapped[Issue] = relationship(lazy="selectin")
    actor: Mapped["User | None"] = relationship(
        lazy="selectin", foreign_keys=[actor_id]
    )


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class OtpRequestLog(Base):
    __tablename__ = "otp_request_log"
    __table_args__ = (
        Index("ix_otp_request_log_phone_created", "phone", "created_at"),
        Index("ix_otp_request_log_ip_created", "ip", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(20))
    ip: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
