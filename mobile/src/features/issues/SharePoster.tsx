import Constants from 'expo-constants';
import { Image } from 'expo-image';
import React, { forwardRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';
import Svg, { Circle, Path } from 'react-native-svg';
import type { Issue } from '../../domain/issue';
import { categoryLabel, severityLabel, shortDay } from '../../domain/issue';
import type { Poster } from '../../domain/poster';
import { CategoryGlyph } from './glyphs';

/** Logical size. Captured at 3x, that is a 1080 × 1920 story image. */
export const POSTER_WIDTH = 360;
export const POSTER_HEIGHT = 640;

/**
 * Where the QR on every poster points: the App Store listing. Set
 * `expo.extra.appStoreUrl` in app.json once the app is live; until then the
 * QR is left off rather than printing a code that goes nowhere.
 */
const APP_STORE_URL: string =
  (Constants.expoConfig?.extra as { appStoreUrl?: string } | undefined)?.appStoreUrl ?? '';

// The poster is always light, whatever theme the phone is in: it is an image
// that leaves the app and lands in someone else's chat.
const INK = '#000000';
const CHALK = '#6e6e73';
const GROUND = '#eceef0';
const SURFACE = '#f2f2f4';
const PIXEL = 'GeistPixel-Square';

type Props = {
  issue: Issue;
  poster: Poster;
  /** Called once the photo has drawn (or failed), so capture waits for it. */
  onReady?: () => void;
};

/** The share ticket. Fixed size and light-only, so the captured image is the
 *  same on every phone. */
export const SharePoster = forwardRef<View, Props>(function SharePoster(
  { issue, poster, onReady },
  ref,
) {
  const [photoFailed, setPhotoFailed] = React.useState(false);
  const photo = !photoFailed ? issue.cover_url : null;
  const { tone } = poster;

  React.useEffect(() => {
    if (!photo) onReady?.();
    // Only on whether there is a photo to wait for.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photo]);

  return (
    <View ref={ref} collapsable={false} style={styles.ground}>
      <View style={styles.card}>
        <View style={styles.top}>
          <View style={styles.headRow}>
            <Text style={styles.wordmark}>UTHAO</Text>
            <View style={styles.badge}>
              <View style={[styles.badgeDot, { backgroundColor: tone.fill }]} />
              <Text style={[styles.badgeText, { color: tone.text }]}>{poster.badge}</Text>
            </View>
          </View>

          <View style={styles.photo}>
            {photo ? (
              <Image
                source={{ uri: photo }}
                style={StyleSheet.absoluteFill}
                contentFit="cover"
                cachePolicy="disk"
                onLoad={() => onReady?.()}
                onError={() => setPhotoFailed(true)}
              />
            ) : (
              // No photo: the category's glyph, drawn light like the rest.
              <View style={styles.noPhoto}>
                <CategoryGlyph category={issue.category} size={44} color={CHALK} />
              </View>
            )}
            <View style={styles.chips}>
              <Text style={[styles.chip, { backgroundColor: '#ffffff', color: INK }]}>
                {categoryLabel[issue.category].toUpperCase()}
              </Text>
              {issue.severity === 'high' && (
                <Text style={[styles.chip, { backgroundColor: '#d93a12', color: '#ffffff' }]}>
                  {severityLabel.high.toUpperCase()}
                </Text>
              )}
            </View>
            {poster.stamp && (
              <View style={[styles.stamp, { borderColor: tone.fill }]}>
                <Text style={[styles.stampText, { color: tone.text }]}>{poster.stamp}</Text>
              </View>
            )}
          </View>

          <Text numberOfLines={3} style={styles.title}>
            {issue.title}
          </Text>

          <View style={styles.placeRow}>
            <Svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={INK} strokeWidth={2.2}>
              <Path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" strokeLinecap="round" strokeLinejoin="round" />
              <Circle cx={12} cy={10} r={3} />
            </Svg>
            <Text numberOfLines={1} style={styles.place}>
              {issue.locality ?? categoryLabel[issue.category]}
              <Text style={styles.placeDate}>{`  ·  Reported ${shortDay(issue.created_at)}`}</Text>
            </Text>
          </View>
        </View>

        {/* The tear: notches on both edges and a dashed line between. */}
        <View style={styles.tear}>
          <View style={[styles.notch, { left: -13 }]} />
          <View style={[styles.notch, { right: -13 }]} />
          <View style={styles.dash} />
        </View>

        <View style={styles.stub}>
          <View style={styles.bigRow}>
            <Text style={styles.big}>{poster.big}</Text>
            <Text style={styles.bigLabel}>{poster.bigLabel}</Text>
          </View>

          <View style={styles.steps}>
            {poster.steps.map((step) => (
              <View key={step.label} style={styles.step}>
                {step.state === 'current' ? (
                  <View style={styles.dashedBar}>
                    {Array.from({ length: 9 }, (_, i) => (
                      <View key={i} style={[styles.dashSeg, { backgroundColor: tone.fill }]} />
                    ))}
                  </View>
                ) : (
                  <View
                    style={[
                      styles.bar,
                      { backgroundColor: step.state === 'done' ? tone.fill : '#e3e4e7' },
                    ]}
                  />
                )}
                <Text
                  numberOfLines={1}
                  style={[
                    styles.stepLabel,
                    step.state === 'current'
                      ? { color: tone.text, fontWeight: '700' }
                      : { color: step.state === 'done' ? INK : CHALK },
                  ]}>
                  {step.label}
                </Text>
              </View>
            ))}
          </View>

          <View style={{ flex: 1 }} />

          <View style={styles.cta}>
            <View style={styles.ctaText}>
              <Text numberOfLines={1} style={styles.ask}>
                {poster.ask}
              </Text>
              <Text numberOfLines={1} style={styles.askSub}>
                {poster.askSub}
              </Text>
            </View>
            {APP_STORE_URL ? (
              <View style={styles.qr}>
                <QRCode value={APP_STORE_URL} size={44} color={INK} backgroundColor="#ffffff" ecl="M" />
              </View>
            ) : null}
          </View>
        </View>
      </View>
    </View>
  );
});

const styles = StyleSheet.create({
  ground: {
    width: POSTER_WIDTH,
    height: POSTER_HEIGHT,
    padding: 18,
    backgroundColor: GROUND,
  },
  card: {
    flex: 1,
    backgroundColor: '#ffffff',
    borderRadius: 22,
    overflow: 'hidden',
  },
  top: { paddingTop: 16, paddingHorizontal: 18, gap: 12 },
  headRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  wordmark: { fontFamily: PIXEL, fontSize: 15, letterSpacing: 1, color: INK },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  badgeDot: { width: 7, height: 7, borderRadius: 4 },
  badgeText: { fontSize: 10, fontWeight: '700', letterSpacing: 0.8 },
  photo: { height: 224, borderRadius: 14, overflow: 'hidden', backgroundColor: SURFACE },
  noPhoto: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  chips: { position: 'absolute', left: 10, top: 10, flexDirection: 'row', gap: 5 },
  chip: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    overflow: 'hidden',
  },
  stamp: {
    position: 'absolute',
    right: 12,
    bottom: 14,
    transform: [{ rotate: '-9deg' }],
    borderWidth: 3,
    borderRadius: 7,
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: 10,
    paddingTop: 5,
    paddingBottom: 3,
  },
  stampText: { fontFamily: PIXEL, fontSize: 22, letterSpacing: 2 },
  title: { fontSize: 22, lineHeight: 25, fontWeight: '700', letterSpacing: -0.6, color: INK, marginTop: 2 },
  placeRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  place: { flexShrink: 1, fontSize: 13, fontWeight: '600', color: INK },
  placeDate: { fontWeight: '500', color: CHALK },
  tear: { height: 30, marginTop: 14 },
  notch: {
    position: 'absolute',
    top: 2,
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: GROUND,
  },
  dash: {
    position: 'absolute',
    left: 22,
    right: 22,
    top: 14,
    borderTopWidth: 2,
    borderStyle: 'dashed',
    borderColor: 'rgba(0,0,0,0.16)',
  },
  stub: { flex: 1, paddingTop: 2, paddingHorizontal: 18, paddingBottom: 16, gap: 14 },
  bigRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 10 },
  big: { fontFamily: PIXEL, fontSize: 52, lineHeight: 46, color: INK },
  bigLabel: { flexShrink: 1, fontSize: 13, lineHeight: 16, fontWeight: '600', color: INK, paddingBottom: 1 },
  steps: { flexDirection: 'row', gap: 5 },
  step: { flex: 1, gap: 5 },
  bar: { height: 5, borderRadius: 3 },
  dashedBar: { height: 5, flexDirection: 'row', gap: 3, overflow: 'hidden', borderRadius: 3 },
  dashSeg: { width: 5, height: 5 },
  stepLabel: { fontSize: 10, fontWeight: '600' },
  cta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: SURFACE,
    borderRadius: 12,
    paddingVertical: 9,
    paddingLeft: 12,
    paddingRight: 9,
    minHeight: 54,
  },
  ctaText: { flex: 1, gap: 2 },
  ask: { fontSize: 12, fontWeight: '700', color: INK },
  askSub: { fontSize: 11, color: '#4b4b50' },
  qr: { backgroundColor: '#ffffff', borderRadius: 7, padding: 4 },
});
