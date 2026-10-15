import { useRouter } from 'expo-router';
import { Camera } from 'lucide-react-native';
import React, { useState } from 'react';
import {
  Dimensions,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { RemoteImage } from '../shell/RemoteImage';
import type { Photo } from '../../domain/issue';
import { shortAge } from '../../domain/issue';
import { Avatar } from '../profile/Avatar';
import { metric, type as t, useTone } from '../../theme/tokens';

const { width } = Dimensions.get('window');

/**
 * Every photo on a report, credited.
 *
 * A civic report gains its weight from several people having stood in the same
 * place at different times, so the credit line is not decoration: it is the
 * difference between one person's claim and a corroborated one. The lead image
 * is large and the rest are a filmstrip, which keeps the original report's
 * framing while making later additions obviously present.
 */
export function Gallery({ photos, onAdd }: { photos: Photo[]; onAdd?: () => void }) {
  const tone = useTone();
  const router = useRouter();
  const [open, setOpen] = useState<number | null>(null);

  if (!photos.length) return null;
  const [lead, ...rest] = photos;
  const usable = (photo: Photo) => !photo.url.startsWith('demo://');

  return (
    <View>
      <Pressable onPress={() => setOpen(0)}>
        {usable(lead) ? (
          <RemoteImage source={{ uri: lead.url }} style={styles.lead} resizeMode="cover" />
        ) : (
          <View style={[styles.lead, styles.placeholder, { backgroundColor: tone.surface }]}>
            <Camera size={28} color={tone.chalk} />
          </View>
        )}
      </Pressable>
      <Credit photo={lead} />

      {(rest.length > 0 || onAdd) && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.strip}>
          {rest.map((photo, index) => (
            <Pressable key={photo.id} onPress={() => setOpen(index + 1)} style={styles.tileWrap}>
              {usable(photo) ? (
                <RemoteImage source={{ uri: photo.thumbnail_url }} style={styles.tile} />
              ) : (
                <View style={[styles.tile, styles.placeholder, { backgroundColor: tone.surface }]}>
                  <Camera size={18} color={tone.chalk} />
                </View>
              )}
              <Pressable
                onPress={() => router.push(`/users/${photo.contributor.id}`)}
                hitSlop={6}
                style={styles.tileAvatar}>
                <Avatar
                  id={photo.contributor.id}
                  name={photo.contributor.display_name}
                  uri={photo.contributor.avatar_url}
                  size={20}
                />
              </Pressable>
            </Pressable>
          ))}

          {onAdd && (
            <Pressable
              onPress={onAdd}
              style={[styles.tile, styles.addTile, { borderColor: tone.hairline }]}>
              <Camera size={20} color={tone.chalk} />
              <Text style={[t.body(11), { color: tone.chalk, marginTop: 4 }]}>Add</Text>
            </Pressable>
          )}
        </ScrollView>
      )}

      <PhotoViewer photos={photos} index={open} onClose={() => setOpen(null)} />
    </View>
  );
}

function Credit({ photo }: { photo: Photo }) {
  const tone = useTone();
  const router = useRouter();
  return (
    <View style={styles.credit}>
      <Pressable
        onPress={() => router.push(`/users/${photo.contributor.id}`)}
        hitSlop={6}
        style={styles.creditPerson}>
        <Avatar id={photo.contributor.id} name={photo.contributor.display_name} uri={photo.contributor.avatar_url} size={22} />
        <Text style={[t.meta(12, '600', 0), { color: tone.ink, marginLeft: 7 }]}>
          {photo.contributor.display_name}
        </Text>
      </Pressable>
      <Text style={[t.meta(12, '500', 0), { color: tone.chalk, marginLeft: 6 }]}>
        {photo.from_report ? 'reported this' : 'added this'}
      </Text>
      <View style={{ flex: 1 }} />
      <Text style={[t.meta(12, '500', 0), { color: tone.chalk }]}>{shortAge(photo.created_at)}</Text>
    </View>
  );
}

/** Full-bleed viewer. Swiping is horizontal paging, same as the strip. */
function PhotoViewer({
  photos,
  index,
  onClose,
}: {
  photos: Photo[];
  index: number | null;
  onClose: () => void;
}) {
  const router = useRouter();
  if (index === null) return null;
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.viewerBackdrop} onPress={onClose}>
        <ScrollView
          horizontal
          pagingEnabled
          contentOffset={{ x: index * width, y: 0 }}
          showsHorizontalScrollIndicator={false}>
          {photos.map((photo) => (
            <View key={photo.id} style={{ width, justifyContent: 'center' }}>
              {!photo.url.startsWith('demo://') && (
                <RemoteImage source={{ uri: photo.url }} style={styles.viewerImage} resizeMode="contain" />
              )}
              <Pressable
                onPress={() => {
                  onClose();
                  router.push(`/users/${photo.contributor.id}`);
                }}
                hitSlop={8}
                style={styles.viewerPerson}>
                <Avatar id={photo.contributor.id} name={photo.contributor.display_name} uri={photo.contributor.avatar_url} size={22} />
                <Text style={[t.meta(12, '600', 0), { color: '#fff', marginLeft: 7 }]}>
                  {photo.contributor.display_name}
                </Text>
              </Pressable>
              <Text style={[t.body(12), { color: '#ffffff99', textAlign: 'center', marginTop: 3 }]}>
                {photo.from_report ? 'Reported this' : 'Added this'}
              </Text>
            </View>
          ))}
        </ScrollView>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  lead: { width: '100%', height: 230, borderRadius: metric.radius },
  placeholder: { alignItems: 'center', justifyContent: 'center' },
  credit: { flexDirection: 'row', alignItems: 'center', marginTop: 10 },
  creditPerson: { flexDirection: 'row', alignItems: 'center' },
  viewerPerson: { flexDirection: 'row', alignItems: 'center', alignSelf: 'center', marginTop: 14 },
  strip: { paddingTop: 12, paddingRight: 4 },
  tileWrap: { marginRight: 8 },
  tile: { width: 74, height: 74, borderRadius: 10 },
  tileAvatar: { position: 'absolute', left: 5, bottom: 5 },
  addTile: {
    borderWidth: 1,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  viewerBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.94)', justifyContent: 'center' },
  viewerImage: { width, height: '70%' },
});
