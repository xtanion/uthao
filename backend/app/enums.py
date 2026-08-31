from enum import StrEnum


class Category(StrEnum):
    POTHOLE_ROAD = "pothole_road"
    GARBAGE = "garbage"
    FOOTPATH = "footpath"
    STREETLIGHT = "streetlight"
    WATER_DRAINAGE = "water_drainage"
    MANHOLE = "manhole"
    TRAFFIC_INFRASTRUCTURE = "traffic_infrastructure"
    FALLEN_TREE = "fallen_tree"
    PUBLIC_PROPERTY = "public_property"
    OTHER = "other"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContactChannel(StrEnum):
    """How a complaint can actually reach a body.

    Most Indian corporations publish a portal and a helpline but no
    complaint mailbox, so this is what says whether a letter can be sent at
    all rather than assuming every authority has an address.
    """

    EMAIL = "email"
    PORTAL = "portal"
    NONE = "none"


class ContactPointKind(StrEnum):
    DEPARTMENT = "department"
    WARD = "ward"


class Status(StrEnum):
    REPORTED = "reported"
    COMMUNITY_VERIFIED = "community_verified"
    SUBMITTED_TO_AUTHORITY = "submitted_to_authority"
    AUTHORITY_ACKNOWLEDGED = "authority_acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLUTION_CLAIMED = "resolution_claimed"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    DUPLICATE = "duplicate"
    REMOVED = "removed"


# Statuses that hide an issue from public reads.
HIDDEN_STATUSES = frozenset({Status.REMOVED})

# Statuses where there is nothing left to organise around.
CLOSED_STATUSES = frozenset({Status.RESOLVED, Status.DUPLICATE, Status.REMOVED})

# Raised with an authority and not yet finished, so worth asking about.
IN_FLIGHT_STATUSES = frozenset(
    {
        Status.SUBMITTED_TO_AUTHORITY,
        Status.AUTHORITY_ACKNOWLEDGED,
        Status.IN_PROGRESS,
        Status.RESOLUTION_CLAIMED,
    }
)

# What an authority can move a report to. Nothing else is theirs to set: they
# cannot remove a report, mark it a duplicate, or send it backwards.
AUTHORITY_STATUSES = frozenset(
    {
        Status.AUTHORITY_ACKNOWLEDGED,
        Status.IN_PROGRESS,
        Status.RESOLUTION_CLAIMED,
        Status.RESOLVED,
    }
)


class ActivityType(StrEnum):
    # One event for one act. A support carries its own words and photos, so
    # what the row says is decided by what the support contained.
    SUPPORT_RECEIVED = "support_received"
    STATUS_CHANGED = "status_changed"
    AUTHORITY_REPLIED = "authority_replied"


class MessageDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class EscalationState(StrEnum):
    """How far a report has got with the body it was raised to."""

    DRAFTED = "drafted"
    SENT = "sent"
    # The channel refused it. The draft is kept so a person can look at it.
    FAILED = "failed"
    # Accepted by the transport, then rejected by the receiving server. The
    # address is wrong and a person has to fix it; retrying will not help.
    BOUNCED = "bounced"
