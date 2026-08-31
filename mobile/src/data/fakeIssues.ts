import type {
  Category,
  Duplicate,
  FixDate,
  FixDates,
  GeoPoint,
  Issue,
  NewIssue,
  Photo,
  Reporter,
  Severity,
  Status,
  Support,
  SupportDraft,
  SupportPage,
} from '../domain/issue';
import type { Notification, NotificationPage } from '../domain/notification';
import type { Account, Profile } from '../domain/profile';
import { REPUTATION_WEIGHTS } from '../domain/profile';
import { CATEGORIES, SEVERITIES, categoryLabel, contributionsOpen } from '../domain/issue';
import type {
  AuthGateway,
  IssuesRepository,
  LocationService,
  NearbyQuery,
  NotificationsRepository,
  FeedPage,
  Page,
  PhotoSource,
  UsersRepository,
} from './repository';
import { DUPLICATE_RADIUS_M, PAGE_SIZE } from './repository';

export const demoLocation: GeoPoint = { latitude: 19.0607, longitude: 72.8362 };

/** Non-zero so the paging spinner is observable; tests set it to 0. */
export let pageLatency = 350;
export const setPageLatency = (ms: number) => {
  pageLatency = ms;
};

const LOCALITIES = [
  'Bandra East', 'Khar Road', 'Santacruz West', 'Dadar TT', 'Sion Circle',
  'Andheri East', 'Mahim Junction', 'Matunga', 'Vile Parle',
];

export const DEMO_USER: Reporter = { id: 'demo-user', display_name: 'Resident 3210' };

const NEIGHBOURS: Reporter[] = [
  { id: 'demo-resident-1', display_name: 'Resident 4821' },
  { id: 'demo-resident-2', display_name: 'Resident 7734' },
  { id: 'demo-resident-3', display_name: 'Resident 1190' },
];

const base = (over: Partial<Issue> & Pick<Issue, 'id' | 'title' | 'description'>): Issue => ({
  category: 'other',
  severity: 'medium',
  status: 'reported',
  latitude: 19.06,
  longitude: 72.83,
  locality: null,
  confirmation_count: 0,
  confirmed_by_me: false,
  comment_count: 0,
  photo_count: 0,
  photo_support_count: 0,
  photo_supports_needed: 2,
  confirmed_at: null,
  contributions_open_at: null,
  photos: null,
  ai_summary: null,
  cover_url: null,
  reporter: NEIGHBOURS[0],
  created_at: new Date().toISOString(),
  ...over,
});

const daysAgo = (d: number) => new Date(Date.now() - d * 864e5).toISOString();

export const demoIssues: Issue[] = [
  base({
    id: 'demo-seed-1',
    reporter: DEMO_USER,
    title: 'Cover missing on the footpath side',
    description: 'Cover missing on the footpath side. Unlit after dark.',
    category: 'manhole',
    severity: 'high',
    status: 'community_verified',
    latitude: 19.0612, longitude: 72.8371,
    locality: 'Bandra East',
    confirmation_count: 7,
    created_at: daysAgo(6),
  }),
  base({
    id: 'demo-seed-2',
    reporter: DEMO_USER,
    title: 'Water collects across both lanes',
    description: 'Water collects across both lanes after any rain.',
    category: 'pothole_road',
    latitude: 19.0598, longitude: 72.8344,
    locality: 'Khar Road',
    confirmation_count: 2,
    created_at: daysAgo(3),
  }),
  base({
    id: 'demo-seed-3',
    reporter: DEMO_USER,
    title: 'Whole stretch dark between the market and the bridge',
    description: 'Whole stretch dark between the market and the bridge.',
    category: 'streetlight',
    severity: 'low',
    status: 'submitted_to_authority',
    latitude: 19.0623, longitude: 72.839,
    locality: 'Santacruz West',
    confirmation_count: 4,
    created_at: daysAgo(2),
  }),
  // Enough volume that the feed actually pages and the cursor gets exercised.
  ...Array.from({ length: 27 }, (_, i) => {
    const category = CATEGORIES[i % CATEGORIES.length] as Category;
    return base({
      id: `demo-seed-${i + 4}`,
      title: `${categoryLabel[category]} reported nearby`,
      description: `Residents flagged a ${categoryLabel[category].toLowerCase()} problem on this stretch. Reported ${i + 1} times this month.`,
      category,
      severity: SEVERITIES[i % SEVERITIES.length] as Severity,
      status: (['reported', 'community_verified', 'submitted_to_authority', 'in_progress'] as Status[])[i % 4],
      latitude: 19.05 + (i % 9) * 0.004,
      longitude: 72.83 + (i % 7) * 0.004,
      locality: LOCALITIES[i % LOCALITIES.length],
      reporter: NEIGHBOURS[i % NEIGHBOURS.length],
      confirmed_by_me: i % 7 === 1,
      confirmation_count: (i * 3) % 14,
      created_at: daysAgo(1 + i * 0.3),
    });
  }),
];

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Demo photos are drawn rather than fetched: the artboard has no network. */
const demoPhoto = (contributor: Reporter, fromReport: boolean, seed: number): Photo => ({
  id: `demo-photo-${seed}`,
  url: `demo://photo/${seed}`,
  thumbnail_url: `demo://photo/${seed}`,
  contributor,
  from_report: fromReport,
  created_at: new Date(Date.now() - seed * 36e5).toISOString(),
});

const metresBetween = (a: GeoPoint, b: GeoPoint) => {
  const dLat = (b.latitude - a.latitude) * 111_195.08;
  const dLng = (b.longitude - a.longitude) * 111_195.08 * Math.cos((a.latitude * Math.PI) / 180);
  return Math.hypot(dLat, dLng);
};

export class FakeIssuesRepository implements IssuesRepository {
  private issues: Issue[];
  private nextId = 0;
  private threads = new Map<string, Support[]>();
  private polls = new Map<string, FixDate[]>();
  private galleries = new Map<string, Photo[]>();

  constructor(seed: Issue[] = demoIssues, private auth?: AuthGateway) {
    this.issues = [...seed];
  }

  /** Lets the fake profile repository read the same mutable list. */
  all(): Issue[] {
    return this.issues;
  }

  private me(): string {
    return this.auth?.currentUserId() ?? DEMO_USER.id;
  }

  async nearby({ category, severity, status, q, cursor, limit = PAGE_SIZE }: NearbyQuery): Promise<Page> {
    await sleep(pageLatency);
    const needle = q?.trim().toLowerCase();
    const matches = this.issues.filter(
      (i) =>
        (!category || i.category === category) &&
        (!severity || i.severity === severity) &&
        (!status || i.status === status) &&
        (!needle ||
          i.title.toLowerCase().includes(needle) ||
          i.description.toLowerCase().includes(needle)),
    );
    return this.page(matches, cursor, limit);
  }

  /** Demo mode never raises anything with an authority. */
  async escalation() {
    return null;
  }

  /** Demo data all sits on one street, so the ladder never has to climb. */
  async feed(_point: GeoPoint, cursor?: string | null): Promise<FeedPage> {
    await sleep(pageLatency);
    const ranked = [...this.visibleIssues()].sort(
      (a, b) =>
        b.photo_support_count - a.photo_support_count ||
        b.created_at.localeCompare(a.created_at),
    );
    const page = this.page(ranked, cursor, PAGE_SIZE);
    return { ...page, radius_m: 500, widened: false };
  }

  private visibleIssues(): Issue[] {
    return this.issues.filter((i) => i.status !== 'removed');
  }

  async mine(cursor?: string | null): Promise<Page> {
    await sleep(pageLatency);
    const me = this.me();
    return this.page(
      this.issues.filter((i) => i.reporter.id === me),
      cursor,
      PAGE_SIZE,
    );
  }

  private page(matches: Issue[], cursor: string | null | undefined, limit: number): Page {
    const offset = Number(cursor ?? 0) || 0;
    const items = matches.slice(offset, offset + limit);
    const consumed = offset + items.length;
    return { items, next_cursor: consumed >= matches.length ? null : String(consumed) };
  }

  async get(id: string) {
    const found = this.issues.find((i) => i.id === id);
    if (!found) throw new Error('That report is no longer available.');
    return found;
  }

  async confirm(id: string) {
    return this.setConfirmed(id, true);
  }

  async unconfirm(id: string) {
    return this.setConfirmed(id, false);
  }

  private setConfirmed(id: string, confirmed: boolean) {
    const index = this.issues.findIndex((i) => i.id === id);
    const current = this.issues[index];
    if (current.confirmed_by_me === confirmed) return current;
    const next: Issue = {
      ...current,
      confirmed_by_me: confirmed,
      confirmation_count: current.confirmation_count + (confirmed ? 1 : -1),
    };
    this.issues[index] = next;
    return next;
  }

  async duplicates(point: GeoPoint, category: Category): Promise<Duplicate[]> {
    await sleep(pageLatency);
    return this.issues
      .filter((i) => i.category === category && i.status !== 'resolved' && i.status !== 'removed')
      .map((issue) => ({ issue, distance_m: metresBetween(point, issue) }))
      .filter((d) => d.distance_m <= DUPLICATE_RADIUS_M)
      .sort((a, b) => a.distance_m - b.distance_m)
      .slice(0, 10);
  }

  async support(id: string, draft: SupportDraft): Promise<Issue> {
    await sleep(pageLatency);
    const index = this.issues.findIndex((i) => i.id === id);
    const current = this.issues[index];
    const me = this.me();
    const author: Reporter = { id: me, display_name: DEMO_USER.display_name };
    const isReporter = current.reporter.id === me;

    const thread = this.threads.get(id) ?? [];
    const existing = thread.find((s) => s.author.id === me);
    const photos = draft.photos.map((_, n) =>
      demoPhoto(author, false, this.nextId * 100 + thread.length * 10 + n),
    );

    if (existing) {
      existing.body = draft.body?.trim() || existing.body;
      existing.photos = [...existing.photos, ...photos];
    } else {
      thread.unshift({
        id: `demo-support-${id}-${thread.length}`,
        body: draft.body?.trim() || null,
        photos,
        author,
        author_is_reporter: isReporter,
        mine: true,
        created_at: new Date().toISOString(),
      });
    }
    this.threads.set(id, thread);
    this.galleries.set(id, [...(await this.photos(id)), ...photos]);

    // Counts derived from the thread, the same way the backend derives them.
    const backers = thread.filter((s) => !s.author_is_reporter);
    const next: Issue = {
      ...current,
      confirmed_by_me: !isReporter,
      confirmation_count: backers.length,
      comment_count: thread.filter((s) => s.body).length,
      photo_count: (this.galleries.get(id) ?? []).length,
    };
    this.issues[index] = next;
    return next;
  }

  async withdrawSupport(id: string): Promise<Issue> {
    await sleep(pageLatency);
    const me = this.me();
    const thread = (this.threads.get(id) ?? []).filter((s) => s.author.id !== me);
    this.threads.set(id, thread);
    this.galleries.set(
      id,
      (this.galleries.get(id) ?? []).filter((p) => p.contributor.id !== me || p.from_report),
    );
    const index = this.issues.findIndex((i) => i.id === id);
    const next: Issue = {
      ...this.issues[index],
      confirmed_by_me: false,
      confirmation_count: thread.filter((s) => !s.author_is_reporter).length,
      comment_count: thread.filter((s) => s.body).length,
      photo_count: (this.galleries.get(id) ?? []).length,
    };
    this.issues[index] = next;
    return next;
  }

  async supports(id: string, cursor?: string | null): Promise<SupportPage> {
    await sleep(pageLatency);
    const thread = this.threads.get(id) ?? [];
    const offset = Number(cursor ?? 0) || 0;
    const items = thread.slice(offset, offset + PAGE_SIZE);
    const consumed = offset + items.length;
    return {
      items,
      next_cursor: consumed >= thread.length ? null : String(consumed),
      total: thread.length,
    };
  }

  async photos(id: string): Promise<Photo[]> {
    const known = this.galleries.get(id);
    if (known) return known;
    const issue = this.issues.find((i) => i.id === id);
    const seeded = issue ? [demoPhoto(issue.reporter, true, 1)] : [];
    this.galleries.set(id, seeded);
    return seeded;
  }

  async fixDates(id: string): Promise<FixDates> {
    await sleep(pageLatency);
    const issue = this.issues.find((i) => i.id === id);
    const rows = [...(this.polls.get(id) ?? [])].sort((a, b) =>
      a.fix_on.localeCompare(b.fix_on),
    );
    return {
      items: rows,
      open: issue ? contributionsOpen(issue) : false,
      opens_at: issue?.contributions_open_at ?? null,
      proposed_by_me: rows.some((r) => r.mine),
      remaining_slots: Math.max(0, 5 - rows.length),
    };
  }

  async proposeFixDate(id: string, fixOn: string, fixTime?: string | null): Promise<FixDates> {
    await sleep(pageLatency);
    const rows = this.polls.get(id) ?? [];
    const existing = rows.find((r) => r.fix_on === fixOn);
    if (existing) {
      if (!existing.voted_by_me) {
        existing.voted_by_me = true;
        existing.vote_count += 1;
        existing.going = [
          { id: this.me(), display_name: DEMO_USER.display_name },
          ...existing.going,
        ];
      }
    } else {
      rows.push({
        id: `demo-day-${id}-${rows.length}`,
        fix_on: fixOn,
        fix_time: fixTime ?? null,
        vote_count: 1,
        going: [{ id: this.me(), display_name: DEMO_USER.display_name }],
        voted_by_me: true,
        proposed_by: { id: this.me(), display_name: DEMO_USER.display_name },
        mine: true,
      });
    }
    this.polls.set(id, rows);
    return this.fixDates(id);
  }

  async voteFixDate(id: string, fixDateId: string, on: boolean): Promise<FixDates> {
    await sleep(pageLatency);
    let rows = this.polls.get(id) ?? [];
    const row = rows.find((r) => r.id === fixDateId);
    if (row) {
      if (on && !row.voted_by_me) {
        row.voted_by_me = true;
        row.vote_count += 1;
        row.going = [
          { id: this.me(), display_name: DEMO_USER.display_name },
          ...row.going,
        ];
      } else if (!on && row.voted_by_me) {
        // The proposer pulling out takes the day with them.
        if (row.mine) rows = rows.filter((r) => r.id !== fixDateId);
        else {
          row.voted_by_me = false;
          row.vote_count -= 1;
        }
      }
    }
    this.polls.set(id, rows);
    return this.fixDates(id);
  }

  async create(draft: NewIssue): Promise<Issue> {
    const issue = base({
      id: `demo-${++this.nextId}`,
      title: draft.title,
      description: draft.description,
      category: draft.category,
      severity: draft.severity,
      latitude: draft.latitude,
      longitude: draft.longitude,
      locality: 'Your location',
      reporter: { id: this.me(), display_name: DEMO_USER.display_name },
      photo_count: draft.photos.length,
      created_at: new Date().toISOString(),
    });
    this.issues.unshift(issue);
    return issue;
  }
}

/** Any phone signs in with [demoOtp]; no SMS provider involved. */
export class FakeAuthGateway implements AuthGateway {
  private userId: string | null;
  constructor(signedInAs: string | null = null, readonly demoOtp = '123456') {
    this.userId = signedInAs;
  }
  /** Demo sessions start fresh every launch; there is nothing to restore. */
  async restore() {}

  currentUserId() {
    return this.userId;
  }
  async requestOtp() {}
  async verifyOtp(_phone: string, code: string) {
    if (code !== this.demoOtp) {
      throw new Error(`Enter ${this.demoOtp} to sign in while in demo mode.`);
    }
    this.userId = 'demo-user';
  }
  async signOut() {
    this.userId = null;
  }
}

export class FixedLocationService implements LocationService {
  constructor(private point: GeoPoint = demoLocation) {}
  async current() {
    return this.point;
  }
}

/** Simulators have no camera, so demo runs hand back a placeholder path. */
export class StubPhotoSource implements PhotoSource {
  private count = 0;
  async captureMany(limit: number) {
    const taken: string[] = [];
    for (let i = 0; i < limit; i += 1) {
      const uri = await this.capture();
      if (uri) taken.push(uri);
    }
    return taken;
  }

  async pickAvatar() {
    return this.capture();
  }

  async capture() {
    return `demo://photo_${++this.count}.jpg`;
  }
}


const summarize = (issue: Issue) => ({
  id: issue.id,
  title: issue.title,
  category: issue.category,
  severity: issue.severity,
  status: issue.status,
  cover_url: issue.cover_url,
  confirmation_count: issue.confirmation_count,
});

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

/** Seeded against the demo user's own reports, mirroring what the backend
 *  writes: a confirmation names its actor, a status change names no one. */
export class FakeNotificationsRepository implements NotificationsRepository {
  private items: Notification[];

  constructor(issues: Issue[] = demoIssues) {
    const owned = issues.filter((i) => i.reporter.id === DEMO_USER.id);
    this.items = owned.flatMap((issue, index) => {
      const rows: Notification[] = [
        {
          id: `demo-note-${index}-a`,
          type: 'support_received',
          read: index > 0,
          actor_name: ['Resident 4821', 'Resident 7734', 'Resident 1190'][index % 3],
          from_status: null,
          to_status: null,
          issue: summarize(issue),
          created_at: minutesAgo(12 + index * 47),
        },
      ];
      if (issue.status === 'community_verified') {
        rows.push({
          id: `demo-note-${index}-b`,
          type: 'status_changed',
          read: false,
          actor_name: null,
          from_status: 'reported',
          to_status: 'community_verified',
          issue: summarize(issue),
          created_at: minutesAgo(4 + index * 31),
        });
      }
      return rows;
    });
    this.items.sort((a, b) => b.created_at.localeCompare(a.created_at));
  }

  async list(cursor?: string | null): Promise<NotificationPage> {
    await sleep(pageLatency);
    const offset = Number(cursor ?? 0) || 0;
    const items = this.items.slice(offset, offset + PAGE_SIZE);
    const consumed = offset + items.length;
    return {
      items,
      next_cursor: consumed >= this.items.length ? null : String(consumed),
      unread_count: this.items.filter((i) => !i.read).length,
    };
  }

  async markRead(ids?: string[]) {
    this.items = this.items.map((item) =>
      !ids || ids.includes(item.id) ? { ...item, read: true } : item,
    );
    return this.items.filter((i) => !i.read).length;
  }
}

/** Profile stats computed from the same in-memory list the feed reads, so the
 *  demo stays self-consistent as issues are created and confirmed. */
export class FakeUsersRepository implements UsersRepository {
  private overrides: { display_name?: string; avatar_url?: string | null } = {};

  constructor(private repo: FakeIssuesRepository) {}

  private visible() {
    return this.repo.all().filter((i) => i.status !== 'removed');
  }

  async profile(userId: string): Promise<Profile> {
    await sleep(pageLatency);
    const theirs = this.visible().filter((i) => i.reporter.id === userId);
    const contributions = {
      posts: theirs.length,
      upvotes_received: theirs.reduce((sum, i) => sum + i.confirmation_count, 0),
      supports_given:
        userId === DEMO_USER.id
          ? this.visible().filter((i) => i.confirmed_by_me).length
          : 0,
      comments_written: 0,
      resolutions: theirs.filter((i) => i.status === 'resolved').length,
    };
    const known = this.repo.all().find((i) => i.reporter.id === userId)?.reporter;
    return {
      id: userId,
      display_name:
        userId === DEMO_USER.id && this.overrides.display_name
          ? this.overrides.display_name
          : known?.display_name ?? DEMO_USER.display_name,
      avatar_url: userId === DEMO_USER.id ? this.overrides.avatar_url ?? null : null,
      reputation:
        contributions.upvotes_received * REPUTATION_WEIGHTS.upvote +
        contributions.posts * REPUTATION_WEIGHTS.post +
        contributions.resolutions * REPUTATION_WEIGHTS.resolution,
      contributions,
      joined_at: new Date(Date.now() - 220 * 864e5).toISOString(),
    };
  }

  async updateName(displayName: string): Promise<Account> {
    this.overrides.display_name = displayName.trim();
    return this.account();
  }

  async setAvatar(uri: string): Promise<Account> {
    this.overrides.avatar_url = uri;
    return this.account();
  }

  async clearAvatar(): Promise<Account> {
    this.overrides.avatar_url = null;
    return this.account();
  }

  private account(): Account {
    return {
      id: DEMO_USER.id,
      display_name: this.overrides.display_name ?? DEMO_USER.display_name,
      avatar_url: this.overrides.avatar_url ?? null,
    };
  }

  async issues(userId: string, cursor?: string | null, status?: Status): Promise<Page> {
    await sleep(pageLatency);
    return this.slice(
      this.visible().filter(
        (i) => i.reporter.id === userId && (!status || i.status === status),
      ),
      cursor,
    );
  }

  async supports(userId: string, cursor?: string | null): Promise<Page> {
    await sleep(pageLatency);
    // The fake only knows the demo user's own confirmations.
    const backed =
      userId === DEMO_USER.id ? this.visible().filter((i) => i.confirmed_by_me) : [];
    return this.slice(backed, cursor);
  }

  private slice(matches: Issue[], cursor?: string | null): Page {
    const offset = Number(cursor ?? 0) || 0;
    const items = matches.slice(offset, offset + PAGE_SIZE);
    const consumed = offset + items.length;
    return { items, next_cursor: consumed >= matches.length ? null : String(consumed) };
  }
}
