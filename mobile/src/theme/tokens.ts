import { useColorScheme } from 'react-native';
import type { TextStyle } from 'react-native';

/** Pure white or pure black ground. The accent leads; `pending` and `progress`
 *  exist only so a report's status reads at a glance. */
export type Tones = {
  bg: string;
  surface: string;
  ink: string;
  chalk: string;
  hairline: string;
  hazard: string;
  accent: string;
  accentSoft: string;
  accentDeep: string;
  pending: string;
  progress: string;
};

export const light: Tones = {
  bg: '#ffffff',
  surface: '#f2f2f4',
  ink: '#000000',
  chalk: '#6e6e73',
  hairline: 'rgba(0,0,0,0.13)',
  hazard: '#d93a12',
  accent: '#0fc47c',
  accentSoft: '#73ffb9',
  accentDeep: '#06965d',
  pending: '#b7791f',
  progress: '#2563eb',
};

export const dark: Tones = {
  bg: '#000000',
  surface: '#17171a',
  ink: '#ffffff',
  chalk: '#9a9aa0',
  hairline: 'rgba(255,255,255,0.18)',
  hazard: '#ff7043',
  accent: '#73ffb9',
  accentSoft: '#a8ffd4',
  accentDeep: '#2fd98f',
  pending: '#f5b942',
  progress: '#6ea8ff',
};

export const useTone = (): Tones =>
  useColorScheme() === 'dark' ? dark : light;

export const metric = { gutter: 18, gap: 12, radius: 10 } as const;

/** Roles are carried by size and weight; the family stays the platform default. */
type Weight = TextStyle['fontWeight'];

export const type = {
  display: (size = 20, weight: Weight = '600'): TextStyle => ({
    fontSize: size,
    fontWeight: weight,
    letterSpacing: size > 22 ? -0.8 : -0.3,
  }),
  body: (size = 15): TextStyle => ({
    fontSize: size,
    lineHeight: size * 1.4,
    letterSpacing: -0.2,
  }),
  /** Tabular figures keep the corroboration numerals from shifting. */
  meta: (size = 11, weight: Weight = '600', tracking = 0.8): TextStyle => ({
    fontSize: size,
    fontWeight: weight,
    letterSpacing: tracking,
    fontVariant: ['tabular-nums'],
  }),
};
