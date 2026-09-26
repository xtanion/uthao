export const CATEGORIES = [
  'pothole_road', 'garbage', 'footpath', 'streetlight', 'water_drainage',
  'manhole', 'traffic_infrastructure', 'fallen_tree', 'public_property', 'other',
] as const;
export type Category = (typeof CATEGORIES)[number];

export const SEVERITIES = ['low', 'medium', 'high'] as const;
export type Severity = (typeof SEVERITIES)[number];

export const STATUSES = [
  'reported', 'community_verified', 'submitted_to_authority',
  'authority_acknowledged', 'in_progress', 'resolution_claimed', 'resolved',
  'reopened', 'duplicate', 'removed',
] as const;
export type Status = (typeof STATUSES)[number];

import { STATUS_META } from './status';

export type Reporter = {
  id: string;
  display_name: string;
};

/** One image in the gallery, credited to whoever took it. */
export type Photo = {
  id: string;
  url: string;
  thumbnail_url: string;
  contributor: Reporter;
  /** True for photos that came with the original report. */
  from_report: boolean;
  created_at: string;
};

export type Issue = {
  id: string;
  title: string;
  description: string;
  category: Category;
  severity: Severity;
  status: Status;
  latitude: number;
  longitude: number;
  locality: string | null;
  confirmation_count: number;
  confirmed_by_me: boolean;
  comment_count: number;
  photo_count: number;
  /** Supports from someone other than the reporter that carried a photo.
   *  Reaching the threshold is what confirms a report. */
  photo_support_count: number;
  /** How many more photo-backed supports would confirm it. Server-computed, so
   *  the confirmation rule lives in exactly one place. */
  photo_supports_needed: number;
  confirmed_at: string | null;
  /** confirmed_at plus the contributions window. Null until confirmed. */
  contributions_open_at: string | null;
  cover_url: string | null;
  /** The whole gallery, on the detail read only. Null in the feed. */
  photos: Photo[] | null;
  ai_summary: string | null;
  reporter: Reporter;
  created_at: string;
};

/** A report close enough that a new one is probably the same thing. */
export type Duplicate = {
  issue: Issue;
  distance_m: number;
};

/** One person backing a report: optional words, optional photos. */
export type Support = {
  id: string;
  body: string | null;
  photos: Photo[];
  author: Reporter;
  author_is_reporter: boolean;
  mine: boolean;
  created_at: string;
};

/** A day somebody has offered to go and fix the thing. */
export type FixDate = {
  id: string;
  fix_on: string;
  /** "HH:MM", or null while only the day is settled. */
  fix_time: string | null;
  vote_count: number;
  /** Who has said they will be there. Capped; vote_count is the true total. */
  going: Reporter[];
  voted_by_me: boolean;
  proposed_by: Reporter;
  mine: boolean;
};

export type FixDates = {
  items: FixDate[];
  open: boolean;
  opens_at: string | null;
  proposed_by_me: boolean;
  remaining_slots: number;
};

export type SupportPage = {
  items: Support[];
  next_cursor: string | null;
  total: number;
};

/** What the composer is holding when it asks about duplicates. */
export type SupportDraft = {
  body?: string;
  photos: string[];
  /** Where the phone is. The server refuses photos without it, or from too far
   *  from the report: they count because they are taken where it is. */
  location?: GeoPoint;
};

export const roundedDistance = (metres: number): string =>
  metres < 1000 ? `${Math.round(metres)} m` : `${(metres / 1000).toFixed(1)} km`;

export type GeoPoint = { latitude: number; longitude: number };

export type NewIssue = {
  client_report_id: string;
  title: string;
  description: string;
  category: Category;
  severity: Severity;
  latitude: number;
  longitude: number;
  photos: string[];
};

export const categoryLabel: Record<Category, string> = {
  pothole_road: 'Pothole / Road',
  garbage: 'Garbage',
  footpath: 'Footpath',
  streetlight: 'Streetlight',
  water_drainage: 'Water / Drainage',
  manhole: 'Manhole',
  traffic_infrastructure: 'Traffic infrastructure',
  fallen_tree: 'Fallen tree',
  public_property: 'Public property',
  other: 'Other',
};

/** Only the top band is named, and only it earns the hazard red. */
export const severityLabel: Record<Severity, string> = {
  high: 'Critical',
  medium: 'Medium',
  low: 'Low',
};

/** Words that stay lowercase inside a title, but not at either end. */
const MINOR = new Set([
  'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in', 'into',
  'nor', 'of', 'on', 'onto', 'or', 'over', 'the', 'to', 'up', 'via', 'with',
]);

/** Title case for report titles, which people type however they like. */
export const titleCase = (value: string): string => {
  const words = value.trim().split(/\s+/);
  return words
    .map((word, i) => {
      // An acronym someone typed deliberately stays as it is.
      if (word.length > 1 && word === word.toUpperCase()) return word;
      const lower = word.toLowerCase();
      const inner = i !== 0 && i !== words.length - 1;
      if (inner && MINOR.has(lower)) return lower;
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(' ');
};

/** Defined in ./status, which is the one place the lifecycle is described. */
export const statusLabel = (status: Status) => STATUS_META[status].label;

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** Hand-rolled rather than Intl: a civic record should read the same on every
 *  device, whatever ICU data that device happens to ship. */
export const fullMoment = (iso: string) => {
  const d = new Date(iso);
  const hours = d.getHours();
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  const minute = String(d.getMinutes()).padStart(2, '0');
  const meridiem = hours < 12 ? 'am' : 'pm';
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()} at ${hour12}:${minute} ${meridiem}`;
};

export type StageKey = 'reported' | 'confirmed' | 'submitted' | 'fixed' | 'contributions';
export type StageState = 'done' | 'current' | 'pending';

export type Stage = {
  key: StageKey;
  label: string;
  caption: string | null;
  state: StageState;
};

/** How far along the trunk each status sits. Two of them are off it entirely:
 *  a duplicate or a removed report is not partway to being fixed. */
const TRUNK: Record<Status, number> = {
  reported: 0,
  community_verified: 1,
  submitted_to_authority: 2,
  authority_acknowledged: 2,
  in_progress: 2,
  reopened: 2,
  resolution_claimed: 3,
  resolved: 3,
  duplicate: -1,
  removed: -1,
};

export const onTrack = (status: Status) => TRUNK[status] >= 0;

/** A short day, for captions: "3 Sept". */
export const shortDay = (iso: string) => {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`;
};

export const contributionsOpen = (issue: Pick<Issue, 'contributions_open_at' | 'status'>) => {
  if (!issue.contributions_open_at) return false;
  if (issue.status === 'resolved' || issue.status === 'duplicate' || issue.status === 'removed') {
    return false;
  }
  return Date.now() >= new Date(issue.contributions_open_at).getTime();
};

const daysUntil = (iso: string) =>
  Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 864e5));

const at = (reached: number, index: number): StageState => {
  if (reached > index) return 'done';
  if (reached === index) return 'current';
  return 'pending';
};

/**
 * The trunk, then the fork. A report is filed, corroborated by people who
 * turned up with cameras, and passed to an authority; after that it is either
 * fixed by them or, when they have not moved on it, handed back to the people
 * who reported it.
 */
export const stagesFor = (
  issue: Pick<
    Issue,
    | 'status'
    | 'photo_support_count'
    | 'photo_supports_needed'
    | 'confirmed_at'
    | 'contributions_open_at'
  >,
  authority: string | null,
): { trunk: Stage[]; fork: Stage[] } => {
  const reached = TRUNK[issue.status];
  const body = authority ?? 'the authority';
  const fixed = reached >= 3;
  const open = contributionsOpen(issue);

  return {
    trunk: [
      { key: 'reported', label: 'Reported', caption: null, state: at(reached, 0) },
      {
        key: 'confirmed',
        label: 'Confirmed',
        caption: issue.confirmed_at
          ? `${issue.photo_support_count} people photographed it too`
          : `${issue.photo_support_count} of ${
              issue.photo_support_count + issue.photo_supports_needed
            } photo confirmations`,
        state: at(reached, 1),
      },
      {
        key: 'submitted',
        label: `Submitted to ${body}`,
        caption: issue.status === 'reopened' ? 'Reopened after a claimed fix' : null,
        state: at(reached, 2),
      },
    ],
    fork: [
      {
        key: 'fixed',
        label: `Fixed by ${body}`,
        caption: issue.status === 'resolution_claimed' ? 'Awaiting confirmation' : null,
        state: fixed ? 'done' : 'pending',
      },
      {
        key: 'contributions',
        label: 'Contributions open',
        caption: open
          ? 'Pick a day below'
          : issue.contributions_open_at
            ? `Opens in ${daysUntil(issue.contributions_open_at)} days`
            : 'Once it is confirmed',
        state: open ? 'current' : 'pending',
      },
    ],
  };
};

export const shortAge = (iso: string) => {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'now';
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
};
