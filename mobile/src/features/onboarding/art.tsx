import { ArrowUp, BadgeCheck, Camera, Eye } from 'lucide-react-native';
import React from 'react';
import { Dimensions, StyleSheet, Text, useColorScheme, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, RadialGradient, Rect, Stop } from 'react-native-svg';
import type { Category, Status } from '../../domain/issue';
import { type as t, useTone } from '../../theme/tokens';
import { CategoryGlyph, StatusGlyph } from '../issues/glyphs';

export const hue = {
  mint: '#2fd98f',
  coral: '#ff7a59',
  amber: '#f5b942',
  sky: '#5b9dff',
  violet: '#a78bfa',
  pink: '#ff6fb1',
} as const;

const STAGE_HEIGHT = Math.min(300, Math.round(Dimensions.get('window').height * 0.36));

/** Three soft colour fields behind each slide's illustration. */
function Backdrop({ id, colours }: { id: string; colours: [string, string, string] }) {
  const strength = useColorScheme() === 'dark' ? 0.55 : 0.42;
  const fields = [
    { cx: '12%', cy: '18%', r: '62%' },
    { cx: '92%', cy: '30%', r: '55%' },
    { cx: '55%', cy: '105%', r: '60%' },
  ];
  return (
    <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
      <Defs>
        {colours.map((colour, i) => (
          <RadialGradient key={i} id={`${id}-${i}`} cx="50%" cy="50%" r="50%">
            <Stop offset="0" stopColor={colour} stopOpacity={strength} />
            <Stop offset="1" stopColor={colour} stopOpacity={0} />
          </RadialGradient>
        ))}
      </Defs>
      {fields.map((field, i) => (
        <Circle key={i} cx={field.cx} cy={field.cy} r={field.r} fill={`url(#${id}-${i})`} />
      ))}
    </Svg>
  );
}

export function Stage({
  id,
  colours,
  children,
}: {
  id: string;
  colours: [string, string, string];
  children: React.ReactNode;
}) {
  const tone = useTone();
  return (
    <View style={[styles.stage, { backgroundColor: tone.surface }]}>
      <Backdrop id={id} colours={colours} />
      {children}
    </View>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: object }) {
  const tone = useTone();
  return (
    <View style={[styles.card, { backgroundColor: tone.bg, borderColor: tone.hairline }, style]}>
      {children}
    </View>
  );
}

const SHOWN: { category: Category; colour: string }[] = [
  { category: 'pothole_road', colour: hue.coral },
  { category: 'manhole', colour: hue.amber },
  { category: 'streetlight', colour: hue.violet },
  { category: 'garbage', colour: hue.mint },
  { category: 'water_drainage', colour: hue.sky },
  { category: 'footpath', colour: hue.pink },
  { category: 'fallen_tree', colour: hue.mint },
  { category: 'traffic_infrastructure', colour: hue.amber },
];

/** What can be reported, as the glyphs the rest of the app uses. */
export function ReportArt() {
  const tone = useTone();
  return (
    <Stage id="report" colours={[hue.coral, hue.amber, hue.mint]}>
      <View style={styles.grid}>
        {SHOWN.map(({ category, colour }, i) => (
          <View
            key={category}
            style={[
              styles.tile,
              {
                backgroundColor: tone.bg,
                borderColor: `${colour}66`,
                transform: [{ rotate: `${(i % 3) - 1}deg` }],
              },
            ]}>
            <View style={[styles.tileWash, { backgroundColor: `${colour}26` }]} />
            <CategoryGlyph category={category} size={26} color={colour} />
          </View>
        ))}
      </View>
      <View style={[styles.shutter, { backgroundColor: tone.accent }]}>
        <Camera size={22} color="#000" />
      </View>
    </Stage>
  );
}

/** The two controls on every card, reproduced at size so they are recognised later. */
export function ActionsArt() {
  const tone = useTone();
  return (
    <Stage id="actions" colours={[hue.sky, hue.violet, hue.mint]}>
      <Card style={{ width: 250 }}>
        <View style={styles.cardMeta}>
          <View style={[styles.metaDot, { backgroundColor: hue.coral }]} />
          <Text style={[t.meta(11, '500', 0), { color: tone.chalk }]}>MG Road · 2h</Text>
        </View>
        <Text style={[t.body(14), { color: tone.ink, marginTop: 6 }]}>
          Open manhole right by the bus stop
        </Text>
        <Svg width="100%" height={64} style={{ marginTop: 10 }}>
          <Defs>
            <LinearGradient id="plate" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor={hue.amber} stopOpacity={0.7} />
              <Stop offset="1" stopColor={hue.coral} stopOpacity={0.55} />
            </LinearGradient>
          </Defs>
          <Rect x={0} y={0} width="100%" height={64} rx={8} fill="url(#plate)" />
        </Svg>
        <View style={styles.pills}>
          <View style={[styles.pill, { backgroundColor: `${tone.accent}2e` }]}>
            <ArrowUp size={16} color={tone.accentDeep} />
            <Text style={[t.meta(13, '600', 0), { color: tone.accentDeep, marginLeft: 5 }]}>12</Text>
          </View>
          <View style={[styles.pill, { borderWidth: 1, borderColor: hue.sky }]}>
            <Eye size={16} color={hue.sky} />
            <Text style={[t.meta(13, '600', 0), { color: hue.sky, marginLeft: 5 }]}>4</Text>
          </View>
        </View>
      </Card>
    </Stage>
  );
}

const PEOPLE = [
  { colour: hue.coral, tilt: '-8deg', label: 'Asha' },
  { colour: hue.sky, tilt: '2deg', label: 'Ravi' },
  { colour: hue.violet, tilt: '9deg', label: 'Meera' },
];

/** Three people, three photographs, one place. */
export function ConfirmArt() {
  const tone = useTone();
  return (
    <Stage id="confirm" colours={[hue.violet, hue.pink, hue.sky]}>
      <View style={styles.polaroids}>
        {PEOPLE.map((person, i) => (
          <View
            key={person.label}
            style={[
              styles.polaroid,
              {
                backgroundColor: tone.bg,
                borderColor: tone.hairline,
                transform: [{ rotate: person.tilt }, { translateY: i === 1 ? -10 : 0 }],
              },
            ]}>
            <View style={[styles.photo, { backgroundColor: `${person.colour}40` }]}>
              <Camera size={20} color={person.colour} />
            </View>
            <View style={styles.byline}>
              <View style={[styles.avatar, { backgroundColor: person.colour }]} />
              <Text style={[t.meta(10, '500', 0), { color: tone.chalk, marginLeft: 5 }]}>
                {person.label}
              </Text>
            </View>
          </View>
        ))}
      </View>
      <View style={[styles.badge, { backgroundColor: tone.bg, borderColor: `${tone.accent}88` }]}>
        <BadgeCheck size={16} color={tone.accentDeep} />
        <Text style={[t.meta(12, '600', 0.2), { color: tone.accentDeep, marginLeft: 6 }]}>
          Confirmed by photo
        </Text>
      </View>
    </Stage>
  );
}

/** Where a confirmed report goes. A compressed StatusTrack. */
export function EscalateArt() {
  const tone = useTone();
  const steps: { status: Status; label: string; note: string; colour: string }[] = [
    { status: 'community_verified', label: 'Confirmed', note: 'by neighbours', colour: hue.violet },
    { status: 'submitted_to_authority', label: 'Sent to the ward', note: 'letter on record', colour: hue.sky },
    { status: 'resolved', label: 'Fixed', note: 'checked by you', colour: hue.mint },
  ];
  return (
    <Stage id="escalate" colours={[hue.sky, hue.mint, hue.violet]}>
      <Card style={{ width: 240, paddingVertical: 18 }}>
        {steps.map((step, i) => (
          <View key={step.label} style={styles.trackRow}>
            <View style={styles.trackMark}>
              <View style={[styles.node, { backgroundColor: step.colour }]}>
                <StatusGlyph status={step.status} size={14} color="#000" />
              </View>
              {i < steps.length - 1 && (
                <View style={[styles.stem, { backgroundColor: `${step.colour}66` }]} />
              )}
            </View>
            <View style={{ marginLeft: 12, marginTop: 2 }}>
              <Text style={[t.display(15, '500'), { color: tone.ink }]}>{step.label}</Text>
              <Text style={[t.meta(11, '400', 0), { color: tone.chalk, marginTop: 1 }]}>
                {step.note}
              </Text>
            </View>
          </View>
        ))}
      </Card>
    </Stage>
  );
}

const NEARBY = [
  { x: 40, y: 52, colour: hue.coral },
  { x: 132, y: 40, colour: hue.amber },
  { x: 146, y: 122, colour: hue.violet },
  { x: 30, y: 128, colour: hue.sky },
];

/** A pin over a soft radius, with what has already been flagged around it. */
export function LocationArt() {
  const tone = useTone();
  return (
    <Stage id="location" colours={[hue.mint, hue.sky, hue.amber]}>
      <Svg width={180} height={180} viewBox="0 0 168 168">
        <Defs>
          <LinearGradient id="halo" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={tone.accentSoft} stopOpacity={0.6} />
            <Stop offset="1" stopColor={tone.accentDeep} stopOpacity={0.2} />
          </LinearGradient>
        </Defs>
        <Circle cx={84} cy={84} r={72} fill="url(#halo)" />
        <Circle cx={84} cy={84} r={46} fill="none" stroke={tone.accentDeep} strokeOpacity={0.4} strokeWidth={1.5} />
        <Circle cx={84} cy={84} r={22} fill="none" stroke={tone.accentDeep} strokeOpacity={0.55} strokeWidth={1.5} />
        {NEARBY.map((dot) => (
          <React.Fragment key={`${dot.x}-${dot.y}`}>
            <Circle cx={dot.x} cy={dot.y} r={9} fill={dot.colour} fillOpacity={0.3} />
            <Circle cx={dot.x} cy={dot.y} r={4.5} fill={dot.colour} />
          </React.Fragment>
        ))}
        <Path
          d="M84 62a15 15 0 0 0-15 15c0 11 15 27 15 27s15-16 15-27a15 15 0 0 0-15-15z"
          fill={tone.ink}
        />
        <Circle cx={84} cy={77} r={5.5} fill={tone.bg} />
      </Svg>
    </Stage>
  );
}

const styles = StyleSheet.create({
  stage: {
    height: STAGE_HEIGHT, borderRadius: 28, overflow: 'hidden',
    alignItems: 'center', justifyContent: 'center',
  },
  card: { borderRadius: 16, borderWidth: 1, padding: 14 },
  grid: {
    flexDirection: 'row', flexWrap: 'wrap', width: 248,
    alignItems: 'center', justifyContent: 'center',
  },
  tile: {
    width: 52, height: 52, borderRadius: 14, borderWidth: 1, margin: 5,
    alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
  },
  tileWash: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  shutter: {
    position: 'absolute', bottom: 18, right: 18, width: 48, height: 48, borderRadius: 24,
    alignItems: 'center', justifyContent: 'center',
  },
  cardMeta: { flexDirection: 'row', alignItems: 'center' },
  metaDot: { width: 7, height: 7, borderRadius: 4, marginRight: 6 },
  pills: { flexDirection: 'row', marginTop: 12, gap: 8 },
  pill: {
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 11, paddingVertical: 6, borderRadius: 999,
  },
  polaroids: { flexDirection: 'row', marginTop: -14 },
  polaroid: { width: 82, padding: 6, paddingBottom: 8, borderRadius: 10, borderWidth: 1, marginHorizontal: -4 },
  photo: { height: 70, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  byline: { flexDirection: 'row', alignItems: 'center', marginTop: 6 },
  avatar: { width: 12, height: 12, borderRadius: 6 },
  badge: {
    position: 'absolute', bottom: 26, flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, borderWidth: 1,
  },
  trackRow: { flexDirection: 'row' },
  trackMark: { alignItems: 'center' },
  node: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  stem: { width: 2, height: 20 },
});
