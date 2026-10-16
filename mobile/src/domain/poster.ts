import type { Escalation } from './escalation';
import type { FixDate, FixDates, Issue, Status } from './issue';
import { contributionsOpen } from './issue';

/**
 * What the share poster says for a report, decided from where it stands.
 *
 * One ticket design, seven states: waiting on photos, confirmed, raised, fix
 * claimed, fixed, and the community path (open for a fix day, a day picked).
 * Reports nobody else can see yet, or ever (in review, rejected, duplicate,
 * removed), have no poster: there is nothing public to share.
 */
export type PosterState =
  | 'reported'
  | 'confirmed'
  | 'raised'
  | 'fix_claimed'
  | 'fixed'
  | 'community_open'
  | 'fix_day_set';

export type PosterTone = { fill: string; text: string };

export type PosterStep = {
  label: string;
  /** done: solid bar; current: dashed bar in the tone; pending: grey. */
  state: 'done' | 'current' | 'pending';
};

export type Poster = {
  state: PosterState;
  tone: PosterTone;
  badge: string;
  /** The big pixel numeral, and the line beside it. */
  big: string;
  bigLabel: string;
  /** Diagonal stamp over the photo, if this state has one. */
  stamp: string | null;
  steps: PosterStep[];
  ask: string;
  askSub: string;
};

// Mirrors the app's status colours: amber waiting, green corroborated or
// fixed, blue with the authority, violet when the community takes it on.
const TONES: Record<'amber' | 'green' | 'blue' | 'violet', PosterTone> = {
  amber: { fill: '#d99a2b', text: '#8a5a12' },
  green: { fill: '#0fc47c', text: '#047a4b' },
  blue: { fill: '#2563eb', text: '#1d4fd8' },
  violet: { fill: '#7c3aed', text: '#6d28d9' },
};

const HIDDEN: Status[] = ['in_review', 'rejected', 'duplicate', 'removed'];
const RAISED: Status[] = [
  'submitted_to_authority',
  'authority_acknowledged',
  'in_progress',
  'reopened',
  'resolution_claimed',
];

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const pad2 = (n: number) => String(Math.max(0, n)).padStart(2, '0');
const hoomans = (n: number) => (n === 1 ? 'hooman' : 'hoomans');
const daysSince = (iso: string, now: number) =>
  Math.max(0, Math.floor((now - new Date(iso).getTime()) / 864e5));

/** "2026-10-25" read as a calendar day where the phone is, not UTC midnight. */
const localDay = (ymd: string) => {
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(y, m - 1, d);
};

/** "Sat 25 Oct", or "Sat 25" when it has to fit a stamp. */
const dayLabel = (ymd: string, short = false) => {
  const d = localDay(ymd);
  return short
    ? `${WEEKDAYS[d.getDay()]} ${d.getDate()}`
    : `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
};

/** "09:00" → "9 am", "18:30" → "6:30 pm". */
const timeLabel = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}${m ? `:${String(m).padStart(2, '0')}` : ''} ${h < 12 ? 'am' : 'pm'}`;
};

/** The day most people have said they'll turn up, still ahead of us. */
const leadingDay = (board: FixDates | null | undefined, now: number): FixDate | null => {
  if (!board) return null;
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const ahead = board.items.filter((row) => row.vote_count > 0 && localDay(row.fix_on) >= today);
  ahead.sort((a, b) => b.vote_count - a.vote_count || a.fix_on.localeCompare(b.fix_on));
  return ahead[0] ?? null;
};

const steps = (done: number, current: number, last?: string): PosterStep[] =>
  ['Reported', 'Confirmed', 'Raised', last ?? 'Fixed'].map((label, i) => ({
    label,
    state: i < done ? 'done' : i === current ? 'current' : 'pending',
  }));

export function posterFor(
  issue: Issue,
  extras: { escalation?: Escalation | null; fixDates?: FixDates | null; now?: number } = {},
): Poster | null {
  if (HIDDEN.includes(issue.status)) return null;
  const now = extras.now ?? Date.now();
  const backers = issue.confirmation_count;
  const raisedAt = extras.escalation?.sent_at ?? issue.confirmed_at;
  const sinceRaised = raisedAt ? daysSince(raisedAt, now) : 0;
  const wasRaised = RAISED.includes(issue.status);

  if (issue.status === 'resolved') {
    return {
      state: 'fixed',
      tone: TONES.green,
      badge: 'FIXED',
      big: pad2(backers),
      bigLabel: `${hoomans(backers)} helped\nget it fixed`,
      stamp: 'FIXED',
      steps: steps(4, -1),
      ask: 'Fixed, together.',
      askSub: 'Report what’s broken on Uthao.',
    };
  }

  if (issue.status === 'resolution_claimed') {
    return {
      state: 'fix_claimed',
      tone: TONES.blue,
      badge: 'FIX CLAIMED',
      big: 'FIX?',
      bigLabel: 'They say it’s done.\nIs it really?',
      stamp: 'FIX?',
      steps: steps(3, 3, 'Fixed?'),
      ask: 'Walk past it?',
      askSub: 'Check if it’s really fixed.',
    };
  }

  if (contributionsOpen(issue)) {
    const day = leadingDay(extras.fixDates, now);
    if (day) {
      const when = day.fix_time ? `${dayLabel(day.fix_on)}, ${timeLabel(day.fix_time)}` : dayLabel(day.fix_on);
      return {
        state: 'fix_day_set',
        tone: TONES.violet,
        badge: 'FIX DAY SET',
        big: pad2(day.vote_count),
        bigLabel: `${hoomans(day.vote_count)} fixing it\n${when}`,
        stamp: dayLabel(day.fix_on, true).toUpperCase(),
        steps: steps(wasRaised ? 3 : 2, 3, dayLabel(day.fix_on)),
        ask: `Join us on ${dayLabel(day.fix_on, true).split(' ')[0]}?`,
        askSub: 'Say you’re going on Uthao.',
      };
    }
    return {
      state: 'community_open',
      tone: TONES.violet,
      badge: 'COMMUNITY FIX',
      big: pad2(sinceRaised),
      bigLabel: `days, no fix.\nTime to do it ourselves.`,
      stamp: 'OUR TURN',
      steps: steps(wasRaised ? 3 : 2, 3, 'Our fix'),
      ask: 'Free this weekend?',
      askSub: 'Pick a day to fix it on Uthao.',
    };
  }

  if (wasRaised) {
    return {
      state: 'raised',
      tone: TONES.blue,
      badge: 'RAISED',
      big: `D-${pad2(sinceRaised)}`,
      bigLabel: 'days since it\nwas raised',
      stamp: null,
      steps: steps(3, 3),
      ask: 'Still not fixed?',
      askSub: 'Back it on Uthao.',
    };
  }

  if (issue.status === 'community_verified') {
    return {
      state: 'confirmed',
      tone: TONES.green,
      badge: 'CONFIRMED',
      big: pad2(backers),
      bigLabel: `${hoomans(backers)} saw this\nwith their own eyes`,
      stamp: null,
      steps: steps(2, 2),
      ask: 'Seen it too?',
      askSub: 'Add your photo on Uthao.',
    };
  }

  const have = issue.photo_support_count;
  return {
    state: 'reported',
    tone: TONES.amber,
    badge: 'NEEDS PHOTOS',
    big: `${have}/${have + issue.photo_supports_needed}`,
    bigLabel: 'photo confirmations\nso far',
    stamp: null,
    steps: steps(1, 1),
    ask: 'Walk past it?',
    askSub: 'Snap it on Uthao to confirm.',
  };
}
