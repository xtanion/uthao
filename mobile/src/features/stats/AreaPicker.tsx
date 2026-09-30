import { Check, ChevronDown, MapPin } from 'lucide-react-native';
import React, { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useStatsAreas } from '../../data/queries';
import { metric, type as t, useTone } from '../../theme/tokens';

export function AreaPicker({
  current,
  onChoose,
}: {
  current: { slug: string; city: string } | null;
  onChoose: (slug: string) => void;
}) {
  const tone = useTone();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const areas = useStatsAreas();
  const options = areas.data ?? [];
  const listed = current && !options.some((o) => o.slug === current.slug)
    ? [{ ...current, reports: 0 }, ...options]
    : options;

  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel={`Area: ${current?.city ?? 'India'}. Change area`}
        style={({ pressed }) => [styles.trigger, { opacity: pressed ? 0.6 : 1 }]}>
        <MapPin size={15} color={tone.chalk} />
        <Text style={[t.display(15, '700'), { color: tone.chalk }]}>{current?.city ?? 'India'}</Text>
        <ChevronDown size={16} color={tone.chalk} />
      </Pressable>

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
        <View style={[styles.sheet, { backgroundColor: tone.bg, paddingBottom: insets.bottom + 12 }]}>
          <View style={styles.grabber}>
            <View style={[styles.grabberBar, { backgroundColor: tone.hairline }]} />
          </View>
          <Text style={[t.display(20, '700'), styles.head, { color: tone.ink }]}>Choose a city</Text>
          {areas.isPending ? (
            <ActivityIndicator color={tone.accentDeep} style={{ paddingVertical: 24 }} />
          ) : (
            <ScrollView style={{ flexGrow: 0 }}>
              {listed.map((option) => {
                const on = option.slug === current?.slug;
                return (
                  <Pressable
                    key={option.slug}
                    onPress={() => {
                      setOpen(false);
                      if (!on) onChoose(option.slug);
                    }}
                    style={({ pressed }) => [
                      styles.row,
                      { borderBottomColor: tone.hairline, opacity: pressed ? 0.6 : 1 },
                    ]}>
                    <View style={{ flex: 1 }}>
                      <Text style={[t.display(16, on ? '700' : '500'), { color: tone.ink }]}>
                        {option.city}
                      </Text>
                      <Text style={[t.meta(12, '500', 0), { color: tone.chalk, marginTop: 2 }]}>
                        {option.reports.toLocaleString('en-IN')} {option.reports === 1 ? 'report' : 'reports'}
                      </Text>
                    </View>
                    {on && <Check size={19} color={tone.accentDeep} />}
                  </Pressable>
                );
              })}
            </ScrollView>
          )}
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start' },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: { maxHeight: '70%', borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  grabber: { alignItems: 'center', paddingTop: 8, paddingBottom: 4 },
  grabberBar: { width: 36, height: 4, borderRadius: 2 },
  head: { paddingHorizontal: metric.gutter, paddingTop: 10, paddingBottom: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: metric.gutter,
    paddingVertical: 14,
    borderBottomWidth: 1,
  },
});
