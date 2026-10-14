import type {
  Category,
  Duplicate,
  FixDates,
  GeoPoint,
  Issue,
  NewIssue,
  Photo,
  Severity,
  Status,
  SupportDraft,
  SupportPage,
} from '../domain/issue';
import type { NotificationPage } from '../domain/notification';
import type { Escalation } from '../domain/escalation';
import type { Period, Stats, StatsAreaOption, StatsContributors, StatsScope } from '../domain/stats';
import type { Account, Profile } from '../domain/profile';

export const PAGE_SIZE = 20;

/** Opaque to the client: it round-trips whatever the backend hands back. */
export type Page = { items: Issue[]; next_cursor: string | null };

/** The home feed, plus how far it had to reach to fill itself.
 *  `radius_m: null` means distance stopped being a filter entirely. */
export type FeedPage = Page & { radius_m: number | null; widened: boolean };

export type NearbyQuery = {
  point: GeoPoint;
  radiusM?: number;
  category?: Category;
  severity?: Severity;
  status?: Status;
  /** Free text over title and description. */
  q?: string;
  cursor?: string | null;
  limit?: number;
};

/** Search reaches further than the feed; 500 m is too tight to find anything. */
export const SEARCH_RADIUS_M = 5000;

/** Matches the backend's DUPLICATE_RADIUS_M default. */
export const DUPLICATE_RADIUS_M = 100;

export interface IssuesRepository {
  nearby(query: NearbyQuery): Promise<Page>;
  /** The home feed: ranked by proximity, freshness and backing, and widened
   *  until it has something to show. */
  feed(point: GeoPoint, cursor?: string | null): Promise<FeedPage>;
  get(id: string): Promise<Issue>;
  confirm(id: string): Promise<Issue>;
  unconfirm(id: string): Promise<Issue>;
  create(draft: NewIssue): Promise<Issue>;
  /** Reports near enough that a new one is probably the same thing. Called
   *  before publishing so the composer can offer to join one instead. */
  duplicates(point: GeoPoint, category: Category): Promise<Duplicate[]>;
  /** Back a report, optionally with words and photos. */
  support(id: string, draft: SupportDraft): Promise<Issue>;
  withdrawSupport(id: string): Promise<Issue>;
  supports(id: string, cursor?: string | null): Promise<SupportPage>;
  photos(id: string): Promise<Photo[]>;
  /** The days people have offered to go and fix it. */
  fixDates(id: string): Promise<FixDates>;
  proposeFixDate(id: string, fixOn: string, fixTime?: string | null): Promise<FixDates>;
  voteFixDate(id: string, fixDateId: string, on: boolean): Promise<FixDates>;
  /** The signed-in reporter's own issues, newest first. */
  mine(cursor?: string | null): Promise<Page>;
  /** The letter raised with the authority. Null until one has been. */
  escalation(id: string): Promise<Escalation | null>;
  stats(scope: StatsScope): Promise<Stats>;
  statsAreas(): Promise<StatsAreaOption[]>;
  topContributors(period: Period, scope: StatsScope): Promise<StatsContributors>;
}

export interface UsersRepository {
  profile(userId: string): Promise<Profile>;
  /** Issues this person filed, newest first. */
  issues(userId: string, cursor?: string | null, status?: Status): Promise<Page>;
  /** Issues this person corroborated, most recently supported first. */
  supports(userId: string, cursor?: string | null): Promise<Page>;
  /** Account edits, which only ever apply to the signed-in person. */
  updateName(displayName: string): Promise<Account>;
  setAvatar(uri: string): Promise<Account>;
  clearAvatar(): Promise<Account>;
}

export interface NotificationsRepository {
  list(cursor?: string | null): Promise<NotificationPage>;
  /** Omit ids to mark the whole feed read. */
  markRead(ids?: string[]): Promise<number>;
}

export interface AuthGateway {
  /** Reloads a stored session. Required rather than optional because startup
   *  has to call it on whichever gateway is in play. */
  restore(): Promise<void>;
  currentUserId(): string | null;
  requestOtp(phone: string): Promise<void>;
  verifyOtp(phone: string, code: string): Promise<void>;
  signOut(): Promise<void>;
}

export interface LocationService {
  current(): Promise<GeoPoint>;
  /** A short street-and-area line for a point, or null when nothing is known. */
  describe(point: GeoPoint): Promise<string | null>;
}

export interface PhotoSource {
  /** Evidence: taken through the app, never chosen from the library. */
  capture(): Promise<string | null>;
  /** A profile picture, which is not evidence and may come from the library. */
  pickAvatar(): Promise<string | null>;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** `blocked` can only be undone from system settings, since the OS will not
 *  show the prompt again; the others are worth a retry. */
export class LocationError extends Error {
  constructor(message: string, readonly reason: 'denied' | 'blocked' | 'disabled' | 'unavailable') {
    super(message);
  }
}
