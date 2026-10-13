import { useRouter } from 'expo-router';
import { ArrowUp, Eye } from 'lucide-react-native';
import React, { useCallback, useRef, useState } from 'react';
import {
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
import { ActionsArt, ConfirmArt, EscalateArt, LocationArt, ReportArt, hue } from './art';

type Slide = {
  key: string;
  art: () => React.ReactElement;
  eyebrow: string;
  colour: string;
  title: string;
  body: string | (() => React.ReactElement);
};

function ActionsLegend() {
  const tone = useTone();
  const rows = [
    {
      icon: <ArrowUp size={16} color={tone.accentDeep} />,
      wash: `${tone.accent}2e`,
      name: 'Support',
      text: 'Open a report and add what you saw, a line or a photo. The arrow counts everyone who did.',
    },
    {
      icon: <Eye size={16} color={hue.sky} />,
      wash: `${hue.sky}2e`,
      name: 'Seen it',
      text: 'One tap to say you have walked past it too. Tap again to take it back.',
    },
  ];
  return (
    <View style={{ marginTop: 14, gap: 14 }}>
      {rows.map((row) => (
        <View key={row.name} style={styles.legendRow}>
          <View style={[styles.legendIcon, { backgroundColor: row.wash }]}>{row.icon}</View>
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={[t.display(15, '600'), { color: tone.ink }]}>{row.name}</Text>
            <Text style={[t.body(14), { color: tone.chalk, marginTop: 2 }]}>{row.text}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

const SLIDES: Slide[] = [
  {
    key: 'report',
    art: ReportArt,
    eyebrow: 'Report',
    colour: hue.coral,
    title: 'See something broken? Snap it.',
    body: 'A missing manhole cover, a dark street, a drain that floods every monsoon. One photo and a line, and it is on the map for everyone nearby.',
  },
  {
    key: 'actions',
    art: ActionsArt,
    eyebrow: 'On every report',
    colour: hue.sky,
    title: 'Two ways to back it up',
    body: ActionsLegend,
  },
  {
    key: 'confirm',
    art: ConfirmArt,
    eyebrow: 'Confirm',
    colour: hue.violet,
    title: 'Photos make it count',
    body: 'When two other people photograph the same spot, the report is confirmed. Proof from several neighbours is much harder to ignore.',
  },
  {
    key: 'escalate',
    art: EscalateArt,
    eyebrow: 'Escalate',
    colour: hue.mint,
    title: 'Then it goes to the ward',
    body: 'Confirmed reports are sent to the authority responsible, and you can read the letter that went out on your behalf. Follow it until it is fixed.',
  },
  {
    key: 'location',
    art: LocationArt,
    eyebrow: 'Nearby',
    colour: hue.amber,
    title: 'Start with what is near you',
    body: 'Your location places a report accurately and shows what has already been flagged around you. It is only shared with a report you choose to file.',
  },
];

export function OnboardingScreen() {
  const tone = useTone();
  const router = useRouter();
  const { location } = useServices();
  const scroller = useRef<ScrollView>(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const width = Dimensions.get('window').width;

  const last = index === SLIDES.length - 1;

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
      <SafeAreaView edges={['top']}>
        <View style={styles.top}>
          {!last && (
            <Pressable onPress={finish} hitSlop={10}>
              <Text style={[t.meta(13, '500', 0.2), { color: tone.chalk }]}>Skip</Text>
            </Pressable>
          )}
        </View>
      </SafeAreaView>

      <ScrollView
        ref={scroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        style={{ flex: 1 }}>
        {SLIDES.map((slide) => (
          <View key={slide.key} style={[styles.slide, { width }]}>
            <View style={styles.art}>{slide.art()}</View>
            <Text style={[t.meta(12, '600', 1), styles.eyebrow, { color: slide.colour }]}>
              {slide.eyebrow}
            </Text>
            <Text style={[t.display(26, '600'), { color: tone.ink }]}>{slide.title}</Text>
            {typeof slide.body === 'string' ? (
              <Text style={[t.body(15.5), { color: tone.chalk, marginTop: 10 }]}>{slide.body}</Text>
            ) : (
              slide.body()
            )}
          </View>
        ))}
      </ScrollView>

      <SafeAreaView edges={['bottom']}>
        <View style={styles.bottom}>
          <View style={styles.dots}>
            {SLIDES.map((slide, i) => (
              <View
                key={slide.key}
                style={[
                  styles.dot,
                  {
                    backgroundColor: i === index ? SLIDES[index].colour : `${tone.ink}22`,
                    width: i === index ? 20 : 7,
                  },
                ]}
              />
            ))}
          </View>

          <Pressable
            onPress={advance}
            disabled={busy}
            style={[styles.cta, { backgroundColor: tone.accent, opacity: busy ? 0.6 : 1 }]}>
            <Text style={[t.display(16, '500'), { color: '#000' }]}>
              {last ? (busy ? 'One moment…' : 'Enable location') : 'Next'}
            </Text>
          </Pressable>

          {last && (
            <Pressable onPress={finish} hitSlop={8} style={styles.later}>
              <Text style={[t.meta(13, '500', 0.2), { color: tone.chalk }]}>Not now</Text>
            </Pressable>
          )}
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  top: {
    height: 40, paddingHorizontal: metric.gutter,
    alignItems: 'flex-end', justifyContent: 'center',
  },
  slide: { paddingHorizontal: metric.gutter, paddingTop: 8 },
  art: { marginBottom: 26 },
  eyebrow: { textTransform: 'uppercase', marginBottom: 8 },
  legendRow: { flexDirection: 'row', alignItems: 'flex-start' },
  legendIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  bottom: { paddingHorizontal: metric.gutter, paddingBottom: 8 },
  dots: { flexDirection: 'row', justifyContent: 'center', marginBottom: 22 },
  dot: { height: 7, borderRadius: 4, marginHorizontal: 3 },
  cta: {
    height: 52, borderRadius: metric.radius,
    alignItems: 'center', justifyContent: 'center',
  },
  later: { alignItems: 'center', paddingVertical: 14 },
});
