import { useRouter } from 'expo-router';
import React, { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';
import { useMapIssues } from '../../data/queries';
import type { GeoPoint } from '../../domain/issue';
import { metric, type as t, useTone } from '../../theme/tokens';
import { CategoryPlate } from './CategoryPlate';
import { CategoryGlyph } from './glyphs';
import { useChrome } from '../shell/chrome';
import { Centered, LoadFailed } from './NearbyFeed';

const PIN_ZOOM_DELTA = 0.02;

export function MapScreen({ point }: { point: GeoPoint }) {
  const tone = useTone();
  const router = useRouter();
  const query = useMapIssues(point);
  const { show, hide, insets } = useChrome();
  const [expanded, setExpanded] = useState(false);

  if (query.isPending) return <Centered><ActivityIndicator color={tone.accentDeep} /></Centered>;
  if (query.isError) return <LoadFailed error={query.error} onRetry={query.refetch} />;

  return (
    <>
      <MapView
        style={StyleSheet.absoluteFill}
        initialRegion={{ ...point, latitudeDelta: 0.06, longitudeDelta: 0.06 }}
        // Moving the map hands the whole screen to the map. onPanDrag is
        // unambiguously the user, and the gesture-gated start event adds pinch
        // zoom; neither fires for the region settling on mount, which would
        // otherwise hide the dock before it had been touched. A tap on open map
        // brings it back, so nothing is ever stranded.
        onPanDrag={hide}
        onRegionChangeStart={(_, details) => details.isGesture === true && hide()}
        onPress={show}
        onRegionChangeComplete={(region) => setExpanded(region.latitudeDelta < PIN_ZOOM_DELTA)}>
        {query.data?.items.map((issue) => (
          <Marker
            key={issue.id}
            coordinate={{ latitude: issue.latitude, longitude: issue.longitude }}
            onPress={() => router.push(`/issues/${issue.id}`)}>
            {expanded ? (
              <View style={[styles.photoPin, { backgroundColor: tone.bg, borderColor: tone.ink }]}>
                <CategoryPlate category={issue.category} severity={issue.severity} height={56} compact />
                <Text numberOfLines={2} style={[t.display(10, '700'), { color: tone.ink, marginTop: 4 }]}>
                  {issue.title}
                </Text>
                <View style={styles.pinCount}>
                  <View style={[styles.dot, { backgroundColor: tone.accent }]} />
                  <Text style={[t.meta(9, '700', 0), { color: tone.ink }]}>{issue.confirmation_count}</Text>
                </View>
              </View>
            ) : (
              <View style={[styles.dotPin, { backgroundColor: tone.accent, borderColor: tone.ink }]}>
                <CategoryGlyph category={issue.category} size={13} color="#000" />
              </View>
            )}
          </Marker>
        ))}
      </MapView>
      {!query.data?.items.length && (
        <View
          pointerEvents="none"
          style={[styles.empty, { top: insets.top + 12, backgroundColor: tone.bg, borderColor: tone.hairline }]}>
          <Text style={[t.meta(12, '700', 0.2), { color: tone.ink }]}>No reports in this area yet</Text>
        </View>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  empty: {
    position: 'absolute', alignSelf: 'center',
    paddingHorizontal: 14, paddingVertical: 9,
    borderWidth: 1, borderRadius: 999,
  },
  photoPin: { width: 124, padding: 3, borderWidth: 1.4, borderRadius: metric.radius },
  pinCount: { flexDirection: 'row', alignItems: 'center', marginTop: 3, marginBottom: 3 },
  dot: { width: 5, height: 5, marginRight: 4 },
  dotPin: {
    width: 24, height: 24, borderRadius: 12, borderWidth: 1.4,
    alignItems: 'center', justifyContent: 'center',
  },
});
