import { useRouter } from 'expo-router';
import { Camera, LogOut, Trash2 } from 'lucide-react-native';
import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useServices } from '../../src/data/context';
import {
  useClearAvatar,
  useProfile,
  useSetAvatar,
  useSignOut,
  useUpdateName,
} from '../../src/data/queries';
import { Avatar } from '../../src/features/profile/Avatar';
import { Centered, Notice } from '../../src/features/issues/NearbyFeed';
import { metric, type as t, useTone } from '../../src/theme/tokens';

const NAME_LIMIT = 40;

export default function EditProfile() {
  const tone = useTone();
  const router = useRouter();
  const { auth, photos } = useServices();
  const userId = auth.currentUserId();

  const profile = useProfile(userId);
  const rename = useUpdateName();
  const setAvatar = useSetAvatar();
  const clearAvatar = useClearAvatar();
  const signOut = useSignOut();

  const [name, setName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!userId) return <Notice text="Sign in to edit your profile." />;
  if (profile.isPending) {
    return (
      <Centered>
        <ActivityIndicator color={tone.accentDeep} />
      </Centered>
    );
  }
  if (profile.isError) return <Notice text={(profile.error as Error).message} />;

  const me = profile.data;
  const draft = name ?? me.display_name;
  const trimmed = draft.trim();
  const dirty = trimmed !== me.display_name && trimmed.length >= 2;
  const busy =
    rename.isPending || setAvatar.isPending || clearAvatar.isPending || signOut.isPending;

  const run = async (task: Promise<unknown>) => {
    setError(null);
    try {
      await task;
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const pick = async () => {
    setError(null);
    try {
      const uri = await photos.pickAvatar();
      if (uri) await setAvatar.mutateAsync(uri);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const leave = () =>
    Alert.alert('Sign out?', 'Your reports stay where they are.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out',
        style: 'destructive',
        onPress: async () => {
          await signOut.mutateAsync();
          router.dismissTo('/');
        },
      },
    ]);

  return (
    <ScrollView contentContainerStyle={{ padding: metric.gutter, paddingBottom: 48 }}>
      <View style={styles.avatarRow}>
        <Avatar id={me.id} name={draft} uri={me.avatar_url} size={82} />
        <View style={styles.avatarActions}>
          <Pressable onPress={pick} style={[styles.chip, { borderColor: tone.hairline }]}>
            <Camera size={15} color={tone.ink} />
            <Text style={[t.meta(12, '600', 0), { color: tone.ink, marginLeft: 6 }]}>
              {me.avatar_url ? 'Change photo' : 'Add photo'}
            </Text>
          </Pressable>
          {me.avatar_url && (
            <Pressable
              onPress={() => run(clearAvatar.mutateAsync())}
              style={[styles.chip, { borderColor: tone.hairline, marginTop: 8 }]}>
              <Trash2 size={15} color={tone.chalk} />
              <Text style={[t.meta(12, '600', 0), { color: tone.chalk, marginLeft: 6 }]}>
                Remove
              </Text>
            </Pressable>
          )}
        </View>
      </View>

      <Text style={[t.meta(12, '600', 0), { color: tone.chalk, marginTop: 28 }]}>
        Display name
      </Text>
      <TextInput
        value={draft}
        onChangeText={setName}
        maxLength={NAME_LIMIT}
        autoCorrect={false}
        style={[
          styles.field,
          { backgroundColor: tone.surface, color: tone.ink, borderColor: tone.hairline },
        ]}
      />
      <Text style={[t.body(13), { color: tone.chalk, marginTop: 8 }]}>
        This is what neighbours see on your reports. Your phone number is never shown.
      </Text>

      {error && (
        <Text style={[t.body(14), { color: tone.hazard, marginTop: 14 }]}>{error}</Text>
      )}

      <Pressable
        disabled={!dirty || busy}
        onPress={() => run(rename.mutateAsync(trimmed))}
        style={[
          styles.cta,
          { backgroundColor: dirty && !busy ? tone.accent : tone.surface },
        ]}>
        <Text
          style={[
            t.display(16, '600'),
            { color: dirty && !busy ? '#000' : tone.chalk },
          ]}>
          {rename.isPending ? 'Saving…' : 'Save name'}
        </Text>
      </Pressable>

      <View style={[styles.divider, { backgroundColor: tone.hairline }]} />

      <Pressable onPress={leave} style={styles.signOut} disabled={busy}>
        <LogOut size={17} color={tone.hazard} />
        <Text style={[t.display(15, '600'), { color: tone.hazard, marginLeft: 9 }]}>
          Sign out
        </Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  avatarRow: { flexDirection: 'row', alignItems: 'center' },
  avatarActions: { marginLeft: 18, flex: 1 },
  chip: {
    flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start',
    borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8,
  },
  field: {
    height: 52, borderRadius: metric.radius, borderWidth: 1,
    paddingHorizontal: 14, marginTop: 10, fontSize: 17,
  },
  cta: {
    height: 50, borderRadius: metric.radius,
    alignItems: 'center', justifyContent: 'center', marginTop: 22,
  },
  divider: { height: 1, marginVertical: 28 },
  signOut: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6 },
});
