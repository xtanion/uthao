import { useRouter } from 'expo-router';
import { Camera, X } from 'lucide-react-native';
import React, { useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { RemoteImage } from '../shell/RemoteImage';
import type { Support } from '../../domain/issue';
import { MAX_PHOTOS, shortAge } from '../../domain/issue';
import { Avatar } from '../profile/Avatar';
import { type as t, useTone } from '../../theme/tokens';

/**
 * What people who went and looked have said.
 *
 * A support is one act, so one row carries whatever came with it: words,
 * photos, or just the fact that somebody stood there and agreed. The bare ones
 * are deliberately quiet rather than hidden - a row that says only "saw this
 * too" is still corroboration, and dropping it would make the thread look
 * thinner than the evidence actually is.
 */
export function SupportList({
  supports,
  loading,
  onMore,
  hasMore,
}: {
  supports: Support[];
  loading: boolean;
  onMore: () => void;
  hasMore: boolean;
}) {
  const tone = useTone();

  if (loading && !supports.length) {
    return (
      <View style={{ paddingVertical: 24 }}>
        <ActivityIndicator color={tone.accentDeep} />
      </View>
    );
  }

  if (!supports.length) {
    return (
      <Text style={[t.body(14), { color: tone.chalk, paddingVertical: 18 }]}>
        Nobody else has been here yet. If you have seen this, add what you saw.
      </Text>
    );
  }

  return (
    <View>
      {supports.map((support) => (
        <SupportRow key={support.id} support={support} />
      ))}
      {hasMore && (
        <Pressable onPress={onMore} style={styles.more}>
          <Text style={[t.display(14, '600'), { color: tone.accentDeep }]}>
            {loading ? 'Loading…' : 'Show older'}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

function SupportRow({ support }: { support: Support }) {
  const tone = useTone();
  const router = useRouter();
  const usable = (url: string) => !url.startsWith('demo://');
  const openAuthor = () => router.push(`/users/${support.author.id}`);

  return (
    <View style={[styles.row, { borderTopColor: tone.hairline }]}>
      <Pressable onPress={openAuthor} hitSlop={4}>
        <Avatar id={support.author.id} name={support.author.display_name} uri={support.author.avatar_url} size={34} />
      </Pressable>

      <View style={{ flex: 1, marginLeft: 11 }}>
        <View style={styles.head}>
          <Pressable onPress={openAuthor} hitSlop={6}>
            <Text style={[t.meta(13, '600', 0), { color: tone.ink }]}>
              {support.author.display_name}
            </Text>
          </Pressable>
          {support.author_is_reporter && (
            <View style={[styles.badge, { backgroundColor: `${tone.accent}2e` }]}>
              <Text style={[t.meta(10, '700', 0), { color: tone.accentDeep }]}>Reporter</Text>
            </View>
          )}
          {support.verifying && (
            <View style={[styles.badge, { backgroundColor: tone.surface }]}>
              <Text style={[t.meta(10, '700', 0), { color: tone.chalk }]}>Verifying</Text>
            </View>
          )}
          <View style={{ flex: 1 }} />
          <Text style={[t.meta(12, '500', 0), { color: tone.chalk }]}>
            {shortAge(support.created_at)}
          </Text>
        </View>

        {support.body ? (
          <Text style={[t.body(15), { color: tone.ink, marginTop: 4 }]}>{support.body}</Text>
        ) : (
          <Text style={[t.body(14), { color: tone.chalk, marginTop: 4, fontStyle: 'italic' }]}>
            {support.photos.length ? 'Added a photo' : 'Independently saw this'}
          </Text>
        )}

        {support.photos.length > 0 && (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingTop: 9 }}>
            {support.photos.map((photo) =>
              usable(photo.thumbnail_url) ? (
                <RemoteImage key={photo.id} source={{ uri: photo.thumbnail_url }} style={styles.photo} />
              ) : (
                <View
                  key={photo.id}
                  style={[styles.photo, styles.placeholder, { backgroundColor: tone.surface }]}>
                  <Camera size={16} color={tone.chalk} />
                </View>
              ),
            )}
          </ScrollView>
        )}
      </View>
    </View>
  );
}

/**
 * Words and photos. A bare "I saw this too" is the arrow beside the count, not
 * this - the two entry points make the same row without overlapping, so there
 * is nothing here that the arrow already does.
 *
 * What the action is called follows from who is asking: somebody who has not
 * backed it yet is offering corroboration along with what they wrote, somebody
 * who already has is adding to it, and the reporter cannot corroborate their
 * own report at all, so for them it is only ever a follow-up.
 */
export function SupportComposer({
  busy,
  supported,
  isReporter,
  onSubmit,
  onPickPhoto,
  attached,
  onDropPhoto,
}: {
  busy: boolean;
  supported: boolean;
  isReporter: boolean;
  onSubmit: (body: string) => void;
  onPickPhoto: () => void;
  attached: string[];
  onDropPhoto: (uri: string) => void;
}) {
  const tone = useTone();
  const [body, setBody] = useState('');
  const ready = !busy && (body.trim().length > 0 || attached.length > 0);
  const full = attached.length >= MAX_PHOTOS;

  const label = isReporter ? 'Post' : supported ? 'Add' : 'Support';
  const placeholder = isReporter
    ? 'Add a follow-up'
    : supported
      ? 'Add to what you said'
      : 'What did you see?';

  return (
    <View style={styles.composer}>
      {attached.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 10 }}>
          {attached.map((uri) => (
            <Pressable key={uri} onPress={() => onDropPhoto(uri)} style={styles.attached}>
              {uri.startsWith('demo://') ? (
                <View style={[styles.photo, styles.placeholder, { backgroundColor: tone.surface }]}>
                  <Camera size={16} color={tone.chalk} />
                </View>
              ) : (
                <Image source={{ uri }} style={styles.photo} />
              )}
              <View style={[styles.drop, { backgroundColor: tone.bg }]}>
                <X size={11} color={tone.ink} />
              </View>
            </Pressable>
          ))}
        </ScrollView>
      )}

      <View style={[styles.composerRow, { borderBottomColor: tone.hairline }]}>
        <Pressable
          onPress={onPickPhoto}
          hitSlop={8}
          disabled={busy || full}
          accessibilityLabel={full ? `${MAX_PHOTOS} photos already attached` : 'Take a photo'}>
          <Camera size={22} color={busy || full ? tone.chalk : tone.ink} />
        </Pressable>

        <TextInput
          style={[styles.input, { color: tone.ink }]}
          value={body}
          onChangeText={setBody}
          multiline
          maxLength={2000}
          placeholder={placeholder}
          placeholderTextColor={tone.chalk}
        />

        <Pressable
          disabled={!ready}
          onPress={() => {
            onSubmit(body.trim());
            setBody('');
          }}
          style={[
            styles.send,
            { backgroundColor: ready ? tone.accent : tone.surface },
          ]}>
          {busy ? (
            <ActivityIndicator size="small" color={tone.ink} />
          ) : (
            <Text style={[t.display(14, '600'), { color: ready ? '#000' : tone.chalk }]}>
              {label}
            </Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', paddingVertical: 15, borderTopWidth: 1 },
  head: { flexDirection: 'row', alignItems: 'center' },
  badge: { marginLeft: 7, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  photo: { width: 92, height: 92, borderRadius: 9, marginRight: 8 },
  placeholder: { alignItems: 'center', justifyContent: 'center' },
  more: { paddingVertical: 16, alignItems: 'center' },
  composer: { marginTop: 4 },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingBottom: 9,
    borderBottomWidth: 1,
  },
  attached: { marginRight: 0 },
  drop: {
    position: 'absolute',
    top: 4,
    right: 12,
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  input: { flex: 1, fontSize: 15, marginHorizontal: 10, maxHeight: 110, paddingTop: 2 },
  send: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    height: 36,
    minWidth: 74,
    paddingHorizontal: 14,
    borderRadius: 18,
  },
});
