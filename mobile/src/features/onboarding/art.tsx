import { ArrowUp, BadgeCheck, Camera, Eye } from 'lucide-react-native';
import React, { useEffect, useMemo, useRef } from 'react';
import { Animated, Dimensions, Easing, StyleSheet, Text, useColorScheme, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, RadialGradient, Rect, Stop } from 'react-native-svg';
import type { Category, Status } from '../../domain/issue';
import { type as t, useTone } from '../../theme/tokens';
import { CategoryGlyph, StatusGlyph } from '../issues/glyphs';
import { useReducedMotion } from '../shell/motion';

export const hue = {
  mint: '#2fd98f',
  coral: '#ff7a59',
  amber: '#f5b942',
  sky: '#5b9dff',
  violet: '#a78bfa',
  pink: '#ff6fb1',
} as const;

const STAGE_HEIGHT = Math.min(300, Math.round(Dimensions.get('window').height * 0.36));

/** One soft light behind the illustration that fades into the page. */
function Glow({ id, colour }: { id: string; colour: string }) {
  const strength = useColorScheme() === 'dark' ? 0.24 : 0.18;
  return (
    <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
      <Defs>
        <RadialGradient id={`${id}-glow`} cx="50%" cy="50%" r="50%">
          <Stop offset="0" stopColor={colour} stopOpacity={strength} />
          <Stop offset="0.55" stopColor={colour} stopOpacity={strength * 0.35} />
          <Stop offset="1" stopColor={colour} stopOpacity={0} />
        </RadialGradient>
      </Defs>
      <Circle cx="50%" cy="50%" r={STAGE_HEIGHT * 0.55} fill={`url(#${id}-glow)`} />
    </Svg>
  );
}

/** The app mark's gradient, stretched to whatever it sits in. */
export function GradientFill({ id, radius }: { id: string; radius: number }) {
  const tone = useTone();
  return (
    <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
      <Defs>
        <LinearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <Stop offset="0" stopColor={tone.accentSoft} />
          <Stop offset="1" stopColor={tone.accentDeep} />
        </LinearGradient>
      </Defs>
      <Rect x={0} y={0} width="100%" height="100%" rx={radius} ry={radius} fill={`url(#${id})`} />
    </Svg>
  );
}

const seeded = (key: string) => {
  let a = [...key].reduce((h, c) => Math.imul(h ^ c.charCodeAt(0), 2654435761), 7);
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
};

const PALETTE = Object.values(hue);

/** Scattered dots and rings that drift slowly. Seeded by slide, so each slide
 *  keeps its own arrangement across renders. */
function Bubbles({ id, count = 11 }: { id: string; count?: number }) {
  const still = useReducedMotion();
  const bubbles = useMemo(() => {
    const random = seeded(id);
    return Array.from({ length: count }, () => {
      const size = 8 + Math.round(random() * 38);
      return {
        size,
        left: `${Math.round(random() * 92)}%` as const,
        top: `${Math.round(random() * 88)}%` as const,
        colour: PALETTE[Math.floor(random() * PALETTE.length)],
        ring: random() < 0.35,
        opacity: 0.35 + random() * 0.45,
        drift: 4 + random() * 8,
        period: 2200 + random() * 2400,
      };
    });
  }, [id, count]);

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {bubbles.map((bubble, i) => (
        <Bubble key={i} {...bubble} still={still} />
      ))}
    </View>
  );
}

function Bubble({
  size, left, top, colour, ring, opacity, drift, period, still,
}: {
  size: number;
  left: `${number}%`;
  top: `${number}%`;
  colour: string;
  ring: boolean;
  opacity: number;
  drift: number;
  period: number;
  still: boolean;
}) {
  const float = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (still) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(float, { toValue: 1, duration: period, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(float, { toValue: 0, duration: period, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [float, period, still]);

  return (
    <Animated.View
      style={{
        position: 'absolute',
        left,
        top,
        width: size,
        height: size,
        borderRadius: size / 2,
        opacity,
        backgroundColor: ring ? 'transparent' : colour,
        borderWidth: ring ? Math.max(2, size / 10) : 0,
        borderColor: colour,
        transform: [{ translateY: float.interpolate({ inputRange: [0, 1], outputRange: [0, -drift] }) }],
      }}
    />
  );
}

export function Stage({
  id,
  glow,
  bubbles = true,
  children,
}: {
  id: string;
  glow?: string;
  bubbles?: boolean;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.stage}>
      {glow && <Glow id={id} colour={glow} />}
      {bubbles && <Bubbles id={id} />}
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

const SAFFRON = '#ff9933';
const INDIA_GREEN = '#138808';
const CHAKRA = '#000080';
const FLAG_W = 216;
const FLAG_H = 144;
const STRIPS = 24;
const STRIP_W = FLAG_W / STRIPS;
const WAVE_STEPS = 8;

function Tricolour() {
  const band = FLAG_H / 3;
  const r = (band * 0.75) / 2;
  const cx = FLAG_W / 2;
  const cy = FLAG_H / 2;
  return (
    <Svg width={FLAG_W} height={FLAG_H}>
      <Rect x={0} y={0} width={FLAG_W} height={band} fill={SAFFRON} />
      <Rect x={0} y={band} width={FLAG_W} height={band} fill="#ffffff" />
      <Rect x={0} y={band * 2} width={FLAG_W} height={band} fill={INDIA_GREEN} />
      <Circle cx={cx} cy={cy} r={r} fill="none" stroke={CHAKRA} strokeWidth={1.6} />
      <Circle cx={cx} cy={cy} r={r * 0.18} fill={CHAKRA} />
      <Path
        d={Array.from({ length: 24 }, (_, i) => {
          const angle = (i * Math.PI * 2) / 24;
          return `M${cx} ${cy}L${cx + Math.cos(angle) * r} ${cy + Math.sin(angle) * r}`;
        }).join('')}
        stroke={CHAKRA}
        strokeWidth={0.9}
      />
    </Svg>
  );
}

/**
 * The tricolour, waving. It is cut into vertical strips that each bob on a
 * sine a little behind the one before, with the swing growing away from the
 * pole and a shade that follows the fold.
 */
export function WelcomeArt() {
  const tone = useTone();
  const still = useReducedMotion();
  const wave = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (still) return;
    const loop = Animated.loop(
      Animated.timing(wave, { toValue: 1, duration: 2600, easing: Easing.linear, useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [wave, still]);

  const steps = Array.from({ length: WAVE_STEPS + 1 }, (_, k) => k / WAVE_STEPS);
  const curve = (phase: number, scale: number, offset = 0) =>
    steps.map((x) => offset + scale * Math.sin(2 * Math.PI * (x - phase)));

  return (
    <Stage id="welcome" bubbles={false} glow={SAFFRON}>
      <View style={styles.flag}>
        <View style={[styles.pole, { backgroundColor: tone.chalk }]} />
        <View style={{ width: FLAG_W, height: FLAG_H + 24, marginTop: 6 }}>
          {Array.from({ length: STRIPS }, (_, i) => {
            const along = i / STRIPS;
            const amplitude = 1 + 9 * along;
            const phase = along * 0.9;
            return (
              <Animated.View
                key={i}
                style={[
                  styles.strip,
                  {
                    left: i * STRIP_W,
                    width: STRIP_W + 0.6,
                    transform: [
                      { translateY: wave.interpolate({ inputRange: steps, outputRange: curve(phase, amplitude) }) },
                    ],
                  },
                ]}>
                <View style={{ position: 'absolute', left: -i * STRIP_W }}>
                  <Tricolour />
                </View>
                <Animated.View
                  style={[
                    StyleSheet.absoluteFill,
                    {
                      backgroundColor: '#000',
                      opacity: wave.interpolate({
                        inputRange: steps,
                        outputRange: curve(phase - 0.25, 0.09 * (0.4 + along), 0.09 * (0.4 + along)),
                      }),
                    },
                  ]}
                />
              </Animated.View>
            );
          })}
        </View>
      </View>
    </Stage>
  );
}

/** What can be reported, as the glyphs the rest of the app uses. */
export function ReportArt() {
  const tone = useTone();
  return (
    <Stage id="report">
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
    <Stage id="actions" glow={hue.sky}>
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
          <Rect x={0} y={0} width="100%" height={64} rx={16} fill="url(#plate)" />
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
    <Stage id="confirm" glow={hue.violet}>
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
    <Stage id="escalate">
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
    <Stage id="location" glow={hue.mint}>
      <Svg width={180} height={180} viewBox="0 0 168 168">
        <Circle cx={84} cy={84} r={72} fill={tone.accent} fillOpacity={0.14} />
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
  flag: { flexDirection: 'row', alignItems: 'flex-start', marginLeft: -20 },
  pole: { width: 5, height: FLAG_H + 70, borderRadius: 3, marginRight: 1 },
  strip: { position: 'absolute', top: 0, height: FLAG_H, overflow: 'hidden' },
  stage: {
    height: STAGE_HEIGHT,
    alignItems: 'center', justifyContent: 'center',
  },
  card: { borderRadius: 24, borderWidth: 1, padding: 16 },
  grid: {
    flexDirection: 'row', flexWrap: 'wrap', width: 248,
    alignItems: 'center', justifyContent: 'center',
  },
  tile: {
    width: 52, height: 52, borderRadius: 26, borderWidth: 1.5, margin: 5,
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
  polaroid: { width: 82, padding: 6, paddingBottom: 8, borderRadius: 18, borderWidth: 1, marginHorizontal: -4 },
  photo: { height: 70, borderRadius: 13, alignItems: 'center', justifyContent: 'center' },
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
