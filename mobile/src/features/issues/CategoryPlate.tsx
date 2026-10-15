import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { RemoteImage } from '../shell/RemoteImage';
import Svg, { Defs, Line, Pattern, Rect } from 'react-native-svg';
import type { Category, Severity } from '../../domain/issue';
import { type Tones, metric, type as t, useTone } from '../../theme/tokens';
import { CategoryGlyph } from './glyphs';

const severityInk = (tone: Tones, severity: Severity) =>
  severity === 'high' ? tone.hazard : severity === 'medium' ? tone.ink : tone.chalk;

/**
 * Stands in for the report photo until the backend serves signed thumbnails.
 * Hazard-tape stripes keep the slot deliberate instead of looking like a
 * failed load.
 */
export function CategoryPlate({
  category,
  severity,
  uri,
  height = 190,
  compact = false,
}: {
  category: Category;
  severity: Severity;
  uri?: string | null;
  height?: number;
  compact?: boolean;
}) {
  const tone = useTone();
  if (uri) {
    return <RemoteImage source={{ uri }} style={[styles.plate, { height }]} resizeMode="cover" />;
  }
  return (
    <View style={[styles.plate, { height, backgroundColor: tone.surface }]}>
      <Svg width="100%" height="100%" style={StyleSheet.absoluteFill}>
        <Defs>
          <Pattern id="hazard" width="26" height="26" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
            <Line x1="0" y1="0" x2="0" y2="26" stroke={severityInk(tone, severity)} strokeOpacity={0.12} strokeWidth={9} />
          </Pattern>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#hazard)" />
      </Svg>
      <View style={styles.center}>
        <CategoryGlyph category={category} size={compact ? 22 : 38} color={tone.ink} />
        {!compact && (
          <Text style={[t.meta(11, '500', 0), { color: tone.chalk, marginTop: 10 }]}>
            Photo pending
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  plate: { width: '100%', borderRadius: metric.radius, overflow: 'hidden' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
