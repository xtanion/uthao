import { Eye, MapPin, Plus } from 'lucide-react-native';
import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { RemoteImage } from '../shell/RemoteImage';
import type { Duplicate } from '../../domain/issue';
import { categoryLabel, roundedDistance, shortAge, titleCase } from '../../domain/issue';
import { metric, type as t, useTone } from '../../theme/tokens';
import { CategoryPlate } from './CategoryPlate';
import { StatusIcon } from './StatusChip';

/**
 * Shown when a report lands on top of one that already exists.
 *
 * The wording matters more than the layout here. Someone who has just
 * photographed a broken thing has done the work; being told "this is a
 * duplicate" reads as a rejection. So the first and largest option is to add
 * what they took to what is already there, filing a second report is still one
 * tap away, and nothing is decided for them.
 */
export function DuplicateSheet({
  visible,
  candidates,
  busy,
  onAddTo,
  onPostNew,
  onDiscard,
}: {
  visible: boolean;
  candidates: Duplicate[];
  busy: boolean;
  onAddTo: (issueId: string) => void;
  onPostNew: () => void;
  onDiscard: () => void;
}) {
  const tone = useTone();
  const many = candidates.length > 1;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onDiscard}>
      <Pressable style={styles.backdrop} onPress={busy ? undefined : onDiscard} />
      <View style={[styles.sheet, { backgroundColor: tone.bg }]}>
        <View style={styles.grabber}>
          <View style={[styles.grabberBar, { backgroundColor: tone.hairline }]} />
        </View>

        <View style={styles.head}>
          <Text style={[t.display(20, '700'), { color: tone.ink }]}>
            {many ? 'Someone already reported these' : 'Someone already reported this'}
          </Text>
          <Text style={[t.body(14), { color: tone.chalk, marginTop: 6 }]}>
            {many
              ? 'Adding your photos to one of these builds the evidence in one place instead of splitting it.'
              : 'Adding your photos here builds the evidence in one place instead of splitting it across two reports.'}
          </Text>
        </View>

        <ScrollView style={{ flexGrow: 0 }} contentContainerStyle={{ paddingBottom: 4 }}>
          {candidates.map(({ issue, distance_m }, row) => (
            <Pressable
              key={issue.id}
              disabled={busy}
              onPress={() => onAddTo(issue.id)}
              style={[
                styles.candidate,
                {
                  borderBottomColor: tone.hairline,
                  borderBottomWidth: row === candidates.length - 1 ? 0 : 1,
                  opacity: busy ? 0.5 : 1,
                },
              ]}>
              <View style={styles.thumb}>
                {issue.cover_url && !issue.cover_url.startsWith('demo://') ? (
                  <RemoteImage source={{ uri: issue.cover_url }} style={styles.thumbImage} />
                ) : (
                  <CategoryPlate
                    category={issue.category}
                    severity={issue.severity}
                    height={66}
                    compact
                  />
                )}
              </View>

              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text numberOfLines={2} style={[t.display(15, '600'), { color: tone.ink }]}>
                  {titleCase(issue.title || categoryLabel[issue.category])}
                </Text>

                <View style={[styles.metaRow, { marginTop: 4 }]}>
                  <MapPin size={12} color={tone.chalk} />
                  <Text style={[t.meta(12, '500', 0), { color: tone.chalk, marginLeft: 4 }]}>
                    {roundedDistance(distance_m)} away
                  </Text>
                  <Text style={[t.meta(12, '400', 0), { color: tone.chalk }]}>{'  ·  '}</Text>
                  <Text style={[t.meta(12, '500', 0), { color: tone.chalk }]}>
                    {shortAge(issue.created_at)}
                  </Text>
                </View>

                <View style={[styles.metaRow, { marginTop: 5 }]}>
                  <Eye size={12} color={tone.accentDeep} />
                  <Text style={[t.meta(12, '600', 0), { color: tone.accentDeep, marginLeft: 2 }]}>
                    {issue.confirmation_count}
                  </Text>
                  <View style={{ marginLeft: 10 }}>
                    <StatusIcon status={issue.status} size={15} />
                  </View>
                </View>
              </View>

              <View style={[styles.add, { backgroundColor: tone.accent }]}>
                <Plus size={18} color="#000" />
              </View>
            </Pressable>
          ))}
        </ScrollView>

        <Pressable
          disabled={busy}
          onPress={onPostNew}
          style={[styles.primary, { backgroundColor: tone.accent, opacity: busy ? 0.5 : 1 }]}>
          <Text style={[t.display(16, '600'), { color: '#000' }]}>
            Report a different problem
          </Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    maxHeight: '84%',
    paddingBottom: 26,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
  },
  grabber: { alignItems: 'center', paddingTop: 8, paddingBottom: 4 },
  grabberBar: { width: 36, height: 4, borderRadius: 2 },
  head: { paddingHorizontal: metric.gutter, paddingTop: 10, paddingBottom: 16 },
  candidate: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: metric.gutter,
    paddingVertical: 12,
  },
  thumb: { width: 66, height: 66, borderRadius: 8, overflow: 'hidden' },
  thumbImage: { width: '100%', height: '100%' },
  metaRow: { flexDirection: 'row', alignItems: 'center' },
  add: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', marginLeft: 10 },
  primary: {
    marginHorizontal: metric.gutter,
    marginTop: 16,
    height: 54,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
