import { useRouter } from 'expo-router';
import { ChevronRight } from 'lucide-react-native';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Dimensions,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useServices } from '../../data/context';
import { markOnboardingSeen } from '../../data/startup';
import { metric, type as t, useTone } from '../../theme/tokens';
import { useReducedMotion } from '../shell/motion';
import { GradientFill, LocationPulse, LyricDrift, STEPS, StepDisc, useStep } from './art';

const PAGES = 3;

function Headline({ children, sub }: { children: React.ReactNode; sub?: string }) {
  const tone = useTone();
  return (
    <View style={styles.headline}>
      <Text style={[styles.big, { color: tone.ink }]}>{children}</Text>
      {sub && <Text style={[t.body(15), { color: tone.chalk, marginTop: 10 }]}>{sub}</Text>}
    </View>
  );
}

/** Re-enters whenever its key changes, so a new step's line slides into place. */
function Rise({ children }: { children: React.ReactNode }) {
  const still = useReducedMotion();
  const enter = useRef(new Animated.Value(still ? 1 : 0)).current;
  useEffect(() => {
    if (still) return;
    Animated.timing(enter, { toValue: 1, duration: 320, useNativeDriver: true }).start();
  }, [still, enter]);
  return (
    <Animated.View
      style={{
        opacity: enter,
        transform: [{ translateY: enter.interpolate({ inputRange: [0, 1], outputRange: [10, 0] }) }],
      }}>
      {children}
    </Animated.View>
  );
}

export function OnboardingScreen() {
  const tone = useTone();
  const router = useRouter();
  const { location } = useServices();
  const scroller = useRef<ScrollView>(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const step = useStep();
  const width = Dimensions.get('window').width;

  const last = index === PAGES - 1;

  const finish = useCallback(async () => {
    await markOnboardingSeen();
    router.replace('/');
  }, [router]);

  const onScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const next = Math.round(event.nativeEvent.contentOffset.x / width);
      if (next !== index) setIndex(next);
    },
    [index, width],
  );

  const advance = async () => {
    if (!last) {
      scroller.current?.scrollTo({ x: width * (index + 1), animated: true });
      return;
    }
    // Asking here rather than on a cold feed means the system dialog arrives
    // with a reason already on screen. A refusal is not a dead end: the feed
    // explains itself, so onboarding finishes either way.
    setBusy(true);
    try {
      await location.current();
    } catch {
      // Declined or unavailable; the feed handles saying so.
    } finally {
      setBusy(false);
      await finish();
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: tone.bg }}>
      <ScrollView
        ref={scroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        style={StyleSheet.absoluteFill}>
        <View style={[styles.page, { width }]}>
          <LyricDrift />
          <SafeAreaView edges={['top']} style={{ flex: 1 }} />
          <Headline>
            Spot the problem,{'\n'}
            <Text style={{ color: tone.accentDeep }}>Be the solution.</Text>
          </Headline>
        </View>

        <View style={[styles.page, { width }]}>
          <SafeAreaView edges={['top']} style={{ flex: 1 }}>
            <StepDisc step={step} />
          </SafeAreaView>
          <Rise key={step}>
            <Headline>{STEPS[step].text}</Headline>
          </Rise>
        </View>

        <View style={[styles.page, { width }]}>
          <SafeAreaView edges={['top']} style={{ flex: 1 }}>
            <LocationPulse />
          </SafeAreaView>
          <Headline sub="Only shared with reports you file.">Start near you.</Headline>
        </View>
      </ScrollView>

      <SafeAreaView edges={['top']} style={styles.topBar} pointerEvents="box-none">
        <View style={styles.top}>
          {!last && (
            <Pressable onPress={finish} hitSlop={10}>
              <Text style={[t.meta(13, '500', 0.2), { color: tone.chalk }]}>Skip</Text>
            </Pressable>
          )}
        </View>
      </SafeAreaView>

      <SafeAreaView edges={['bottom']} style={styles.bottomBar}>
        <View style={styles.bottom}>
          {last ? (
            <>
              <Pressable
                onPress={advance}
                disabled={busy}
                style={({ pressed }) => [
                  styles.pill,
                  { opacity: busy ? 0.6 : 1, transform: [{ scale: pressed ? 0.97 : 1 }] },
                ]}>
                <GradientFill id="cta-pill" radius={30} />
                <Text style={[t.display(16, '500'), { color: '#000' }]}>
                  {busy ? 'One moment…' : 'Enable location'}
                </Text>
              </Pressable>
              <Pressable onPress={finish} hitSlop={8} style={styles.later}>
                <Text style={[t.meta(13, '500', 0.2), { color: tone.chalk }]}>Not now</Text>
              </Pressable>
            </>
          ) : (
            <View style={styles.footer}>
              <View style={styles.dots}>
                {Array.from({ length: PAGES }, (_, i) => (
                  <View
                    key={i}
                    style={[
                      styles.dot,
                      {
                        backgroundColor: i === index ? tone.accent : `${tone.ink}22`,
                        width: i === index ? 22 : 8,
                      },
                    ]}
                  />
                ))}
              </View>
              <Pressable
                onPress={advance}
                accessibilityLabel="Next"
                style={({ pressed }) => [styles.next, { transform: [{ scale: pressed ? 0.92 : 1 }] }]}>
                <GradientFill id="cta-next" radius={32} />
                <ChevronRight size={28} color="#000" strokeWidth={2.4} />
              </Pressable>
            </View>
          )}
        </View>
      </SafeAreaView>
    </View>
  );
}

const BOTTOM_CLEARANCE = 176;

const styles = StyleSheet.create({
  page: { flex: 1, paddingBottom: BOTTOM_CLEARANCE },
  headline: { paddingHorizontal: metric.gutter },
  big: { fontSize: 42, lineHeight: 48, fontWeight: '600', letterSpacing: -1 },
  topBar: { position: 'absolute', top: 0, left: 0, right: 0 },
  top: {
    height: 40, paddingHorizontal: metric.gutter,
    alignItems: 'flex-end', justifyContent: 'center',
  },
  bottomBar: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  bottom: { paddingHorizontal: metric.gutter, paddingBottom: 8, paddingTop: 12 },
  footer: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingBottom: 14 },
  dots: { flexDirection: 'row' },
  dot: { height: 8, borderRadius: 4, marginRight: 6 },
  next: { width: 64, height: 64, alignItems: 'center', justifyContent: 'center' },
  pill: { height: 60, alignItems: 'center', justifyContent: 'center' },
  later: { alignItems: 'center', paddingVertical: 14 },
});
