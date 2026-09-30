import React from 'react';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

/**
 * Lucide ships no filled glyphs, so the filled states are drawn from the
 * upstream Lucide paths (ISC) with fill turned on. The house merges body and
 * door into one evenodd path so the door stays a knockout.
 */
const HOUSE_BODY =
  'M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z';
const HOUSE_DOOR = 'M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8';
const BELL_BODY =
  'M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326';
const BELL_CLAPPER = 'M10.268 21a2 2 0 0 0 3.464 0';
const SEARCH_HANDLE = 'm21 21-4.34-4.34';

export type NavIconName = 'house' | 'search' | 'chart' | 'bell';

const CHART_BARS = [
  { x: 3.5, y: 13, height: 7.5 },
  { x: 10, y: 3.5, height: 17 },
  { x: 16.5, y: 8.5, height: 12 },
];

export function NavIcon({
  name,
  filled,
  color,
  size = 25,
}: {
  name: NavIconName;
  filled: boolean;
  color: string;
  size?: number;
}) {
  const stroke = { stroke: color, strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };

  if (name === 'house') {
    return (
      <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        {filled ? (
          <Path
            d={`${HOUSE_BODY} ${HOUSE_DOOR}`}
            fill={color}
            fillRule="evenodd"
            stroke={color}
            strokeWidth={1.5}
            strokeLinejoin="round"
          />
        ) : (
          <>
            <Path d={HOUSE_DOOR} {...stroke} />
            <Path d={HOUSE_BODY} {...stroke} />
          </>
        )}
      </Svg>
    );
  }

  if (name === 'chart') {
    return (
      <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        {CHART_BARS.map((bar) => (
          <Rect
            key={bar.x}
            x={bar.x}
            y={bar.y}
            width={4}
            height={bar.height}
            rx={1.2}
            {...stroke}
            fill={filled ? color : 'none'}
          />
        ))}
      </Svg>
    );
  }

  if (name === 'bell') {
    return (
      <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <Path d={BELL_CLAPPER} {...stroke} fill={filled ? color : 'none'} />
        <Path d={BELL_BODY} {...stroke} fill={filled ? color : 'none'} />
      </Svg>
    );
  }

  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path d={SEARCH_HANDLE} {...stroke} strokeWidth={filled ? 2.5 : 2} />
      <Circle cx={11} cy={11} r={8} {...stroke} strokeWidth={filled ? 2.5 : 2} fill={filled ? color : 'none'} />
    </Svg>
  );
}
