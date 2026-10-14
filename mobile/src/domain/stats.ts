import type { Category, GeoPoint } from './issue';

/** Cumulative: a fixed report also counts as confirmed and raised. */
export type StatsTotals = {
  reported: number;
  confirmed: number;
  raised: number;
  resolved: number;
  photos: number;
  contributors: number;
  emails_sent: number;
};

export type StatsWeek = { week_start: string; reported: number; resolved: number };

export type StatsCategory = { category: Category; total: number; resolved: number };

export type StatsPoint = { latitude: number; longitude: number; resolved: boolean };

export type StatsArea = {
  slug: string;
  city: string;
  min_latitude: number;
  max_latitude: number;
  min_longitude: number;
  max_longitude: number;
};

export type StatsAreaOption = { slug: string; city: string; reports: number };

/** A chosen city wins; otherwise the server picks from the point, falling
 *  back to the busiest city. */
export type StatsScope = { area: string | null; point: GeoPoint | null };

export type StatsContributor = {
  id: string;
  display_name: string;
  avatar_url: string | null;
  reputation: number;
  reports: number;
  resolutions: number;
};

/** `area` is null only when no city has been set up at all. */
export type Stats = {
  area: StatsArea | null;
  totals: StatsTotals;
  weeks: StatsWeek[];
  categories: StatsCategory[];
  points: StatsPoint[];
  generated_at: string;
};

export const PERIODS = ['day', 'month', 'year'] as const;
export type Period = (typeof PERIODS)[number];

export const periodLabel: Record<Period, string> = {
  day: 'Today',
  month: 'This month',
  year: 'This year',
};

export type StatsContributors = {
  period: Period;
  since: string;
  area: StatsArea | null;
  items: StatsContributor[];
};

const UNITS = [
  { size: 1e9, suffix: 'B' },
  { size: 1e6, suffix: 'M' },
  { size: 1e3, suffix: 'K' },
];

/** 999, 1.2K, 12K, 340K, 1.5M. One decimal only while it still adds
 *  information, and a value that rounds up to 1000 of a unit moves to the next. */
export function compactCount(n: number): string {
  const abs = Math.abs(n);
  if (abs < 1000) return String(Math.round(n));
  for (let i = UNITS.length - 1; i >= 0; i -= 1) {
    const { size, suffix } = UNITS[i];
    const scaled = abs / size;
    const shown = scaled < 10 ? Math.round(scaled * 10) / 10 : Math.round(scaled);
    if (shown < 1000 || i === 0) {
      return `${n < 0 ? '-' : ''}${shown}${suffix}`;
    }
  }
  return String(n);
}
