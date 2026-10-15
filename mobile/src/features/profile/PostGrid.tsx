import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { RemoteImage } from '../shell/RemoteImage';
import type { Issue } from '../../domain/issue';
import { type as t, useTone } from '../../theme/tokens';
import { CategoryGlyph, StatusGlyph } from '../issues/glyphs';

export const GRID_COLUMNS = 3;
const HAIRLINE_GAP = 1.5;

/**
 * One cell of the posts grid. The photo is the point, so it fills the tile;
 * a report still waiting on its thumbnail falls back to the category glyph
 * rather than an empty square.
 */
export function PostTile({ issue, onPress }: { issue: Issue; onPress: () => void }) {
  const tone = useTone();
  return (
    <Pressable onPress={onPress} style={styles.cell}>
      <View style={[styles.tile, { backgroundColor: tone.surface }]}>
        {issue.cover_url ? (
          <RemoteImage source={{ uri: issue.cover_url }} style={styles.image} resizeMode="cover" />
        ) : (
          <View style={styles.fallback}>
            <CategoryGlyph category={issue.category} size={22} color={tone.chalk} />
          </View>
        )}

        <View style={[styles.corner, { backgroundColor: `${tone.ink}b8` }]}>
          <StatusGlyph status={issue.status} size={12} color={tone.bg} />
        </View>

        {issue.confirmation_count > 0 && (
          <View style={[styles.count, { backgroundColor: `${tone.ink}b8` }]}>
            <Text style={[t.meta(10, '700', 0), { color: tone.bg }]}>
              {issue.confirmation_count}
            </Text>
          </View>
        )}

        {issue.severity === 'high' && (
          <View style={[styles.hazard, { backgroundColor: tone.hazard }]} />
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  cell: { flex: 1 / GRID_COLUMNS, aspectRatio: 1, padding: HAIRLINE_GAP },
  tile: { flex: 1, overflow: 'hidden' },
  image: { width: '100%', height: '100%' },
  fallback: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  corner: {
    position: 'absolute', top: 5, left: 5, width: 20, height: 20,
    borderRadius: 10, alignItems: 'center', justifyContent: 'center',
  },
  count: {
    position: 'absolute', bottom: 5, right: 5, minWidth: 18, height: 18,
    borderRadius: 9, paddingHorizontal: 5,
    alignItems: 'center', justifyContent: 'center',
  },
  hazard: { position: 'absolute', top: 0, right: 0, width: 5, height: 5 },
});
