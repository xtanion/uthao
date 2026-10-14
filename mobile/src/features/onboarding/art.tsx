import { BadgeCheck, Camera, Eye, MapPin, Send } from 'lucide-react-native';
import type { LucideIcon } from 'lucide-react-native';
import React, { useEffect, useRef, useState } from 'react';
import { Animated, Dimensions, Easing, StyleSheet, Text, useColorScheme, View } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import { type as t, useTone } from '../../theme/tokens';
import { useReducedMotion } from '../shell/motion';
import { LYRICS } from './lyrics';

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

/** Milliseconds per point of travel, so speed holds whatever the verse length. */
const LYRIC_PACE = 75;

/** Lyrics drifting upward behind the headline, barely darker than the page. */
export function LyricDrift() {
  const dark = useColorScheme() === 'dark';
  const tone = useTone();
  const still = useReducedMotion();
  const [block, setBlock] = useState(0);
  const drift = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!block || still) return;
    drift.setValue(0);
    const loop = Animated.loop(
      Animated.timing(drift, {
        toValue: -block, duration: block * LYRIC_PACE, easing: Easing.linear, useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [block, still, drift]);

  const copies = block ? Math.ceil(Dimensions.get('window').height / block) + 1 : 1;
  const ink = dark ? '#161618' : '#f0f0f3';
  const verse = (measure: boolean) => (
    <View onLayout={measure ? (e) => setBlock(e.nativeEvent.layout.height) : undefined}>
      {LYRICS.map((line, i) => (
        <Text key={i} style={[t.display(24, '500'), styles.lyric, { color: ink }]}>
          {line}
        </Text>
      ))}
    </View>
  );

  return (
    <View pointerEvents="none" style={[StyleSheet.absoluteFill, { overflow: 'hidden' }]}>
      <Animated.View style={{ transform: [{ translateY: drift }] }}>
        {verse(true)}
        {Array.from({ length: copies }, (_, i) => (
          <React.Fragment key={i}>{verse(false)}</React.Fragment>
        ))}
      </Animated.View>
      <Svg style={styles.fade} width="100%" height="100%">
        <Defs>
          <LinearGradient id="lyric-fade" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={tone.bg} stopOpacity={0} />
            <Stop offset="1" stopColor={tone.bg} stopOpacity={1} />
          </LinearGradient>
        </Defs>
        <Rect x={0} y={0} width="100%" height="100%" fill="url(#lyric-fade)" />
      </Svg>
    </View>
  );
}

export const STEPS: { icon: LucideIcon; text: string }[] = [
  { icon: Camera, text: 'Snap it.' },
  { icon: Eye, text: 'Neighbours confirm.' },
  { icon: Send, text: 'Sent to the ward.' },
  { icon: BadgeCheck, text: 'Fixed.' },
];
const STEP_MS = 2000;

/** The whole loop of the app, one beat at a time. */
export function useStep() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setStep((s) => (s + 1) % STEPS.length), STEP_MS);
    return () => clearInterval(timer);
  }, []);
  return step;
}

export function StepDisc({ step }: { step: number }) {
  const tone = useTone();
  const still = useReducedMotion();
  const enter = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (still) return;
    enter.setValue(0);
    Animated.spring(enter, { toValue: 1, stiffness: 220, damping: 16, mass: 0.8, useNativeDriver: true }).start();
  }, [step, still, enter]);

  const Icon = STEPS[step].icon;
  return (
    <View style={styles.centre}>
      <Animated.View
        style={[
          styles.disc,
          {
            opacity: enter,
            transform: [{ scale: enter.interpolate({ inputRange: [0, 1], outputRange: [0.82, 1] }) }],
          },
        ]}>
        <GradientFill id="step-disc" radius={70} />
        <Icon size={56} color="#000" strokeWidth={1.8} />
      </Animated.View>
      <View style={styles.segments}>
        {STEPS.map((s, i) => (
          <View
            key={s.text}
            style={[styles.segment, { backgroundColor: i === step ? tone.accent : tone.hairline }]}
          />
        ))}
      </View>
    </View>
  );
}

/** A pin with a slow pulse, the only motion on the last page. */
export function LocationPulse() {
  const tone = useTone();
  const still = useReducedMotion();
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (still) return;
    const loop = Animated.loop(
      Animated.timing(pulse, { toValue: 1, duration: 2200, easing: Easing.out(Easing.quad), useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [still, pulse]);

  return (
    <View style={styles.centre}>
      {!still && (
        <Animated.View
          style={[
            styles.ring,
            {
              backgroundColor: tone.accent,
              opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0] }),
              transform: [{ scale: pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.9] }) }],
            },
          ]}
        />
      )}
      <View style={styles.disc}>
        <GradientFill id="pin-disc" radius={70} />
        <MapPin size={56} color="#000" strokeWidth={1.8} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  lyric: { paddingHorizontal: 18, lineHeight: 40 },
  fade: { position: 'absolute', left: 0, right: 0, bottom: 0, height: '55%' },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  disc: { width: 140, height: 140, alignItems: 'center', justifyContent: 'center' },
  ring: { position: 'absolute', width: 140, height: 140, borderRadius: 70 },
  segments: { flexDirection: 'row', gap: 6, marginTop: 36 },
  segment: { width: 22, height: 4, borderRadius: 2 },
});
