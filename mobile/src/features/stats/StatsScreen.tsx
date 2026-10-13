import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { ChevronRight } from 'lucide-react-native';
import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  useColorScheme,
  View,
} from 'react-native';
import MapView, { Circle as GeoCircle } from 'react-native-maps';
import Svg, { Line, Rect } from 'react-native-svg';
import { useLocation, useStats, useTopContributors } from '../../data/queries';
import { categoryLabel, shortDay } from '../../domain/issue';
import type { Period, Stats, StatsArea, StatsCategory, StatsPoint, StatsScope, StatsWeek } from '../../domain/stats';
import { PERIODS, periodLabel } from '../../domain/stats';
import { metric, type Tones, type as t, useTone } from '../../theme/tokens';
import { CategoryGlyph } from '../issues/glyphs';
import { Centered, LoadFailed } from '../issues/NearbyFeed';
import { Avatar } from '../profile/Avatar';
import { useChromeOnScroll, useChromeSpacing } from '../shell/chrome';
import { AreaPicker } from './AreaPicker';

const CATEGORY_ROWS = 6;

const percent = (fraction: number) => `${Math.round(fraction * 100)}%`;

export function StatsScreen({ onOpenMap }: { onOpenMap: () => void }) {
  const tone = useTone();
  const location = useLocation();
  const [chosen, setChosen] = useState<string | null>(null);
  const scope: StatsScope = { area: chosen, point: location.data ?? null };
  const stats = useStats(scope, Boolean(chosen) || !location.isPending);
  const client = useQueryClient();
  const chrome = useChromeOnScroll();
  const spacing = useChromeSpacing(40);

  if (stats.isPending) {
    return (
      <Centered>
        <ActivityIndicator color={tone.accentDeep} />
      </Centered>
    );
  }
  if (stats.isError) return <LoadFailed error={stats.error} onRetry={stats.refetch} />;

  const data = stats.data;
  return (
    <Animated.ScrollView
      {...chrome}
      contentContainerStyle={spacing}
      refreshControl={
        <RefreshControl
          refreshing={stats.isRefetching && !stats.isPlaceholderData}
          onRefresh={() => client.invalidateQueries({ queryKey: ['stats'] })}
          tintColor={tone.accentDeep}
          progressViewOffset={spacing.paddingTop}
        />
      }>
      <Hero stats={data} onChoose={setChosen} />
      <View style={{ opacity: stats.isPlaceholderData ? 0.45 : 1 }}>
        {data.totals.reported ? (
          <>
            <Tiles stats={data} />
            <FixMap area={data.area} points={data.points} onOpen={onOpenMap} />
            <Funnel stats={data} />
            <Weekly weeks={data.weeks} />
            <Categories rows={data.categories} />
            <Contributors scope={scope} />
          </>
        ) : (
          <Text style={[t.body(15), styles.empty, { color: tone.chalk }]}>
            Nothing reported here yet.
          </Text>
        )}
      </View>
    </Animated.ScrollView>
  );
}

function Pills<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  label: (option: T) => string;
}) {
  const tone = useTone();
  return (
    <View style={[styles.periods, { backgroundColor: tone.surface }]}>
      {options.map((option) => {
        const on = option === value;
        return (
          <Pressable
            key={option}
            onPress={() => onChange(option)}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            style={[styles.period, on && { backgroundColor: tone.bg, borderColor: tone.hairline }]}>
            <Text style={[t.meta(12, on ? '600' : '500', 0), { color: on ? tone.ink : tone.chalk }]}>
              {label(option)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const tone = useTone();
  return (
    <View style={styles.section}>
      <Text style={[t.display(18, '600'), { color: tone.ink }]}>{title}</Text>
      <View style={{ marginTop: 14 }}>{children}</View>
    </View>
  );
}

const count = (n: number, one: string, many: string) =>
  ({ value: n.toLocaleString('en-IN'), label: n === 1 ? one : many });

function Hero({ stats, onChoose }: { stats: Stats; onChoose: (slug: string) => void }) {
  const tone = useTone();
  return (
    <View style={styles.hero}>
      <AreaPicker current={stats.area} onChoose={onChoose} />
      <View style={styles.headline}>
        <Text style={[t.display(64, '600'), { color: tone.ink }]}>
          {stats.totals.resolved.toLocaleString('en-IN')}
        </Text>
        <Text style={[t.display(20, '500'), { color: tone.accentDeep }]}>Fixed So Far</Text>
      </View>
    </View>
  );
}

function Tiles({ stats }: { stats: Stats }) {
  const tone = useTone();
  const { totals } = stats;
  const tiles = [
    count(totals.reported, 'issue submitted', 'issues submitted'),
    count(totals.contributors, 'helping hand', 'helping hands'),
    count(totals.photos, 'photo submitted', 'photos submitted'),
    count(totals.emails_sent, 'email sent', 'emails sent'),
  ];
  return (
    <View style={[styles.tiles, { borderBottomColor: tone.hairline }]}>
      {tiles.map((tile) => (
        <View key={tile.label} style={[styles.tile, { backgroundColor: tone.surface }]}>
          <Text style={[t.display(26, '600'), { color: tone.ink }]}>{tile.value}</Text>
          <Text style={[t.meta(12, '500', 0), { color: tone.chalk, marginTop: 2 }]}>{tile.label}</Text>
        </View>
      ))}
    </View>
  );
}

const regionFor = (area: StatsArea | null, points: StatsPoint[]) => {
  const lats = area ? [area.min_latitude, area.max_latitude] : points.map((p) => p.latitude);
  const lngs = area ? [area.min_longitude, area.max_longitude] : points.map((p) => p.longitude);
  const [minLat, maxLat] = [Math.min(...lats), Math.max(...lats)];
  const [minLng, maxLng] = [Math.min(...lngs), Math.max(...lngs)];
  return {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLng + maxLng) / 2,
    latitudeDelta: Math.max((maxLat - minLat) * 1.05, 0.03),
    longitudeDelta: Math.max((maxLng - minLng) * 1.05, 0.03),
  };
};

const YELLOW = '#f5c542';

/** Static on purpose: a live map inside a scroll view fights the scroll for
 *  the finger. Circles rather than Markers keep hundreds of points cheap. */
function FixMap({
  area,
  points,
  onOpen,
}: {
  area: StatsArea | null;
  points: StatsPoint[];
  onOpen: () => void;
}) {
  const tone = useTone();
  const dark = useColorScheme() === 'dark';
  const region = useMemo(() => regionFor(area, points), [area, points]);
  const radius = Math.max(region.latitudeDelta * 111_000 * 0.009, 18);
  // Open first so the fixed ones are drawn on top.
  const ordered = useMemo(
    () => [...points].sort((a, b) => Number(a.resolved) - Number(b.resolved)),
    [points],
  );
  if (!points.length) return null;

  return (
    <Section title="Where things got fixed">
      <Pressable onPress={onOpen} style={[styles.mapFrame, { borderColor: tone.hairline }]}>
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <MapView
            style={StyleSheet.absoluteFill}
            initialRegion={region}
            liteMode
            userInterfaceStyle={dark ? 'dark' : 'light'}
            scrollEnabled={false}
            zoomEnabled={false}
            rotateEnabled={false}
            pitchEnabled={false}
            toolbarEnabled={false}>
            {ordered.map((p, i) => (
              <GeoCircle
                key={i}
                center={{ latitude: p.latitude, longitude: p.longitude }}
                radius={radius}
                fillColor={p.resolved ? tone.accent : YELLOW}
                strokeColor={p.resolved ? tone.accentDeep : '#c99a1a'}
                strokeWidth={1}
                zIndex={p.resolved ? 2 : 1}
              />
            ))}
          </MapView>
        </View>
        <View style={[styles.mapCta, { backgroundColor: tone.bg, borderColor: tone.hairline }]}>
          <Text style={[t.meta(11, '600', 0.2), { color: tone.ink }]}>Open map</Text>
          <ChevronRight size={14} color={tone.ink} />
        </View>
      </Pressable>
      <View style={styles.legend}>
        <Key colour={tone.accent} label="Fixed" tone={tone} />
        <Key colour={YELLOW} label="Still open" tone={tone} />
      </View>
    </Section>
  );
}

function Funnel({ stats }: { stats: Stats }) {
  const tone = useTone();
  const { totals } = stats;
  const stages = [
    { label: 'Reported', value: totals.reported, colour: tone.pending },
    { label: 'Confirmed by neighbours', value: totals.confirmed, colour: `${tone.accent}8c` },
    { label: 'Raised with the authority', value: totals.raised, colour: tone.progress },
    { label: 'Fixed', value: totals.resolved, colour: tone.accent },
  ];
  return (
    <Section title="From report to fix">
      {stages.map((stage) => {
        const share = totals.reported ? stage.value / totals.reported : 0;
        return (
          <View key={stage.label} style={styles.stage}>
            <View style={styles.stageHead}>
              <Text style={[t.body(14), { color: tone.ink, flex: 1 }]}>{stage.label}</Text>
              <Text style={[t.meta(13, '600', 0), { color: tone.ink }]}>
                {stage.value.toLocaleString('en-IN')}
              </Text>
              <Text style={[t.meta(12, '500', 0), styles.stageShare, { color: tone.chalk }]}>
                {percent(share)}
              </Text>
            </View>
            <View style={[styles.track, { backgroundColor: tone.surface }]}>
              <View
                style={[
                  styles.fill,
                  { width: `${Math.max(share * 100, stage.value ? 2 : 0)}%`, backgroundColor: stage.colour },
                ]}
              />
            </View>
          </View>
        );
      })}
    </Section>
  );
}

const CHART_HEIGHT = 120;

function Weekly({ weeks }: { weeks: StatsWeek[] }) {
  const tone = useTone();
  const [width, setWidth] = useState(0);
  const peak = Math.max(1, ...weeks.flatMap((w) => [w.reported, w.resolved]));
  const slot = width / Math.max(weeks.length, 1);
  const bar = Math.min(9, slot * 0.3);
  const height = (value: number) => (value ? Math.max((value / peak) * CHART_HEIGHT, 3) : 0);

  return (
    <Section title="Last 12 weeks">
      <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
        {width > 0 && (
          <Svg width={width} height={CHART_HEIGHT + 1}>
            {weeks.map((week, i) => {
              const centre = slot * i + slot / 2;
              return (
                <React.Fragment key={week.week_start}>
                  <Rect
                    x={centre - bar - 1}
                    y={CHART_HEIGHT - height(week.reported)}
                    width={bar}
                    height={height(week.reported)}
                    rx={2}
                    fill={tone.chalk}
                    opacity={0.45}
                  />
                  <Rect
                    x={centre + 1}
                    y={CHART_HEIGHT - height(week.resolved)}
                    width={bar}
                    height={height(week.resolved)}
                    rx={2}
                    fill={tone.accent}
                  />
                </React.Fragment>
              );
            })}
            <Line x1={0} x2={width} y1={CHART_HEIGHT + 0.5} y2={CHART_HEIGHT + 0.5} stroke={tone.hairline} />
          </Svg>
        )}
      </View>
      <View style={styles.axis}>
        <Text style={[t.meta(10.5, '500', 0), { color: tone.chalk }]}>
          {weeks.length ? shortDay(`${weeks[0].week_start}T00:00:00`) : ''}
        </Text>
        <Text style={[t.meta(10.5, '500', 0), { color: tone.chalk }]}>This week</Text>
      </View>
      <View style={styles.legend}>
        <Key colour={tone.chalk} faded label="Reported" tone={tone} />
        <Key colour={tone.accent} label="Fixed" tone={tone} />
      </View>
    </Section>
  );
}

function Key({ colour, label, faded, tone }: { colour: string; label: string; faded?: boolean; tone: Tones }) {
  return (
    <View style={styles.key}>
      <View style={[styles.swatch, { backgroundColor: colour, opacity: faded ? 0.45 : 1 }]} />
      <Text style={[t.meta(11, '600', 0), { color: tone.chalk }]}>{label}</Text>
    </View>
  );
}

function Categories({ rows }: { rows: StatsCategory[] }) {
  const tone = useTone();
  const shown = rows.slice(0, CATEGORY_ROWS);
  return (
    <Section title="What gets reported">
      {shown.map((row) => (
        <View key={row.category} style={styles.category}>
          <View style={[styles.glyph, { backgroundColor: tone.surface }]}>
            <CategoryGlyph category={row.category} size={15} color={tone.ink} />
          </View>
          <View style={{ flex: 1 }}>
            <View style={styles.stageHead}>
              <Text numberOfLines={1} style={[t.body(14), { color: tone.ink, flex: 1 }]}>
                {categoryLabel[row.category]}
              </Text>
              <Text style={[t.meta(12, '600', 0), { color: tone.chalk }]}>
                <Text style={{ color: tone.accentDeep }}>{row.resolved}</Text> / {row.total}
              </Text>
            </View>
            <View style={[styles.track, { backgroundColor: tone.surface }]}>
              <View
                style={[
                  styles.fill,
                  { width: `${(row.resolved / row.total) * 100}%`, backgroundColor: tone.accent },
                ]}
              />
            </View>
          </View>
        </View>
      ))}
    </Section>
  );
}

const EMPTY_BOARD: Record<Period, string> = {
  day: 'Nobody has reported or backed anything yet today.',
  month: 'Nobody has reported or backed anything yet this month.',
  year: 'Nobody has reported or backed anything yet this year.',
};

function Contributors({ scope }: { scope: StatsScope }) {
  const tone = useTone();
  const router = useRouter();
  const [period, setPeriod] = useState<Period>('month');
  const board = useTopContributors(period, scope);
  const rows = board.data?.items ?? [];

  return (
    <Section title="Top contributors">
      <Pills options={PERIODS} value={period} onChange={setPeriod} label={(p) => periodLabel[p]} />
      {board.isPending ? (
        <ActivityIndicator color={tone.accentDeep} style={{ paddingVertical: 24 }} />
      ) : board.isError ? (
        <Pressable onPress={() => board.refetch()} style={{ paddingVertical: 18 }}>
          <Text style={[t.body(14), { color: tone.chalk }]}>
            Could not load the board. <Text style={{ color: tone.accentDeep }}>Try again</Text>
          </Text>
        </Pressable>
      ) : !rows.length ? (
        <Text style={[t.body(14), { color: tone.chalk, paddingVertical: 18 }]}>
          {EMPTY_BOARD[period]}
        </Text>
      ) : null}
      <View style={{ opacity: board.isPlaceholderData ? 0.45 : 1 }}>
        {rows.map((row, i) => (
          <Pressable
            key={row.id}
            onPress={() => router.push(`/users/${row.id}`)}
            style={({ pressed }) => [
              styles.person,
              { borderBottomColor: tone.hairline, opacity: pressed ? 0.6 : 1 },
            ]}>
            <Text
              style={[
                t.display(15, '600'),
                styles.rank,
                { color: i === 0 ? tone.accentDeep : tone.chalk },
              ]}>
              {i + 1}
            </Text>
            <Avatar id={row.id} name={row.display_name} uri={row.avatar_url} size={36} />
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text numberOfLines={1} style={[t.display(15, '600'), { color: tone.ink }]}>
                {row.display_name}
              </Text>
              <Text style={[t.meta(12, '500', 0), { color: tone.chalk, marginTop: 1 }]}>
                {row.reports} {row.reports === 1 ? 'report' : 'reports'} · {row.resolutions} fixed
              </Text>
            </View>
            <Text style={[t.meta(14, '600', 0), { color: tone.ink }]}>{row.reputation}</Text>
          </Pressable>
        ))}
      </View>
    </Section>
  );
}

const styles = StyleSheet.create({
  hero: { paddingHorizontal: metric.gutter, paddingTop: 20 },
  headline: { flexDirection: 'row', alignItems: 'baseline', gap: 12, marginTop: 10 },
  empty: { paddingHorizontal: metric.gutter, paddingTop: 28 },
  tiles: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    paddingHorizontal: metric.gutter,
    paddingTop: 14,
    paddingBottom: 24,
    borderBottomWidth: 1,
  },
  tile: {
    flexGrow: 1,
    flexBasis: '40%',
    borderRadius: metric.radius,
    paddingVertical: 14,
    paddingHorizontal: 14,
  },
  section: { paddingHorizontal: metric.gutter, paddingTop: 30 },
  mapFrame: {
    height: 210,
    borderRadius: metric.radius,
    borderWidth: 1,
    overflow: 'hidden',
  },
  mapCta: {
    position: 'absolute',
    right: 10,
    bottom: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    paddingLeft: 11,
    paddingRight: 7,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
  },
  stage: { marginBottom: 14 },
  stageHead: { flexDirection: 'row', alignItems: 'baseline', marginBottom: 6 },
  stageShare: { width: 44, textAlign: 'right' },
  track: { height: 8, borderRadius: 4, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  legend: { flexDirection: 'row', gap: 16, marginTop: 10 },
  key: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  swatch: { width: 10, height: 10, borderRadius: 2 },
  category: { flexDirection: 'row', alignItems: 'center', marginBottom: 14 },
  glyph: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  periods: { flexDirection: 'row', borderRadius: 999, padding: 3, marginBottom: 6 },
  period: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  person: { flexDirection: 'row', alignItems: 'center', paddingVertical: 11, borderBottomWidth: 1 },
  rank: { width: 26 },
});
