import { Stack, useRouter } from 'expo-router';
import { Camera, Check } from 'lucide-react-native';
import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useServices } from '../../data/context';
import { useConfirm, useProfile, useUserIssues, useUserSupports } from '../../data/queries';
import type { Issue } from '../../domain/issue';
import type { Contributions, Profile } from '../../domain/profile';
import { REPUTATION_WEIGHTS, joinedLabel, standing } from '../../domain/profile';
import { metric, type as t, useTone } from '../../theme/tokens';
import { IssueCard } from '../issues/IssueCard';
import { Centered, Notice } from '../issues/NearbyFeed';
import { Avatar } from './Avatar';
import { GRID_COLUMNS, PostTile } from './PostGrid';

const TABS = ['Posts', 'Resolutions', 'Supports'] as const;
type Tab = 0 | 1 | 2;

export function ProfileScreen({ userId }: { userId: string }) {
  const tone = useTone();
  const router = useRouter();
  const { auth } = useServices();
  const confirm = useConfirm();
  const [tab, setTab] = useState<Tab>(0);

  const profile = useProfile(userId);
  const posts = useUserIssues(userId);
  const resolutions = useUserIssues(userId, 'resolved');
  const supports = useUserSupports(userId);

  const isMe = auth.currentUserId() === userId;
  const feed = tab === 2 ? supports : tab === 1 ? resolutions : posts;

  const items = useMemo<Issue[]>(
    () => feed.data?.pages.flatMap((p) => p.items) ?? [],
    [feed.data],
  );

  const onConfirm = useCallback(
    (issue: Issue) => {
      if (!auth.currentUserId()) {
        router.push('/auth');
        return;
      }
      confirm.mutate({ id: issue.id, confirmed: issue.confirmed_by_me });
    },
    [auth, confirm, router],
  );

  if (profile.isPending) {
    return (
      <Centered>
        <ActivityIndicator color={tone.accentDeep} />
      </Centered>
    );
  }
  if (profile.isError) return <Notice text={(profile.error as Error).message} />;

  const grid = tab !== 2;

  return (
    <FlatList
      // numColumns cannot change on a live list, so each tab gets its own.
      key={tab}
      data={items}
      numColumns={grid ? GRID_COLUMNS : 1}
      keyExtractor={(issue) => issue.id}
      contentContainerStyle={{ paddingBottom: 48 }}
      refreshControl={
        <RefreshControl
          refreshing={profile.isRefetching}
          onRefresh={() => {
            profile.refetch();
            feed.refetch();
          }}
          tintColor={tone.accentDeep}
        />
      }
      ListHeaderComponent={
        <View>
          {isMe && (
            <Stack.Screen
              options={{
                headerRight: () => (
                  <Pressable onPress={() => router.push('/profile/edit')} hitSlop={8} style={styles.edit}>
                    <Text style={[t.display(15, '500'), { color: tone.ink }]}>Edit profile</Text>
                  </Pressable>
                ),
              }}
            />
          )}
          <Header profile={profile.data} isMe={isMe} />
          <View style={[styles.tabs, { borderBottomColor: tone.hairline }]}>
            {TABS.map((label, i) => (
              <Pressable key={label} style={styles.tab} onPress={() => setTab(i as Tab)}>
                <Text
                  style={[
                    t.display(14, '600'),
                    { color: i === tab ? tone.ink : tone.chalk },
                  ]}>
                  {label}
                </Text>
                <View
                  style={[
                    styles.indicator,
                    { backgroundColor: i === tab ? tone.accent : 'transparent' },
                  ]}
                />
              </Pressable>
            ))}
          </View>
        </View>
      }
      ListEmptyComponent={
        feed.isPending ? (
          <View style={{ paddingVertical: 34 }}>
            <ActivityIndicator color={tone.accentDeep} />
          </View>
        ) : feed.isError ? (
          <Empty text={(feed.error as Error).message} />
        ) : (
          <Empty text={emptyText(tab, isMe)} />
        )
      }
      onEndReachedThreshold={0.6}
      onEndReached={() =>
        feed.hasNextPage && !feed.isFetchingNextPage && feed.fetchNextPage()
      }
      ListFooterComponent={
        feed.isFetchingNextPage ? (
          <View style={{ paddingVertical: 26 }}>
            <ActivityIndicator color={tone.accentDeep} />
          </View>
        ) : null
      }
      renderItem={({ item }) =>
        grid ? (
          <PostTile issue={item} onPress={() => router.push(`/issues/${item.id}`)} />
        ) : (
          <IssueCard
            issue={item}
            onPress={() => router.push(`/issues/${item.id}`)}
            onConfirm={() => onConfirm(item)}
          />
        )
      }
    />
  );
}

function Header({ profile, isMe }: { profile: Profile; isMe: boolean }) {
  const tone = useTone();
  const joined = joinedLabel(profile.joined_at);
  return (
    <View style={styles.header}>
      <View style={styles.identity}>
        <View style={[styles.ring, { borderColor: tone.accent }]}>
          <Avatar
            id={profile.id}
            name={profile.display_name}
            uri={profile.avatar_url}
            size={64}
          />
        </View>
        <View style={{ flex: 1, marginLeft: 16 }}>
          <Text numberOfLines={2} style={[t.display(26, '600'), { color: tone.ink }]}>
            {profile.display_name}
          </Text>
          {!!joined && (
            <Text style={[t.body(14), { color: tone.chalk, marginTop: 2 }]}>Joined {joined}</Text>
          )}
        </View>
      </View>

      <Reputation profile={profile} isMe={isMe} />
      <Journey contributions={profile.contributions} isMe={isMe} />
    </View>
  );
}

/**
 * The score with its own arithmetic printed underneath. A number nobody can
 * account for invites suspicion; this one shows its work, the same reason the
 * issue detail spells out its corroboration count.
 */
function Reputation({ profile, isMe }: { profile: Profile; isMe: boolean }) {
  const tone = useTone();
  const router = useRouter();
  const { photos } = useServices();
  const capturing = useRef(false);
  const { upvotes_received, posts, resolutions } = profile.contributions;
  const parts = [
    { value: upvotes_received, weight: REPUTATION_WEIGHTS.upvote, label: 'confirmations' },
    { value: posts, weight: REPUTATION_WEIGHTS.post, label: 'reports' },
    { value: resolutions, weight: REPUTATION_WEIGHTS.resolution, label: 'resolved' },
  ].filter((part) => part.value > 0);

  const report = async () => {
    if (capturing.current) return;
    capturing.current = true;
    try {
      const shot = await photos.capture();
      if (shot) router.push({ pathname: '/report', params: { photos: JSON.stringify([shot]) } });
    } catch (e) {
      Alert.alert('Could not open the camera', (e as Error).message);
    } finally {
      capturing.current = false;
    }
  };

  return (
    <View style={[styles.score, { backgroundColor: tone.surface }]}>
      <View style={styles.scoreHead}>
        <View>
          <Text style={[t.meta(13, '500', 0.2), { color: tone.chalk }]}>Reputation</Text>
          <Text style={[t.display(40, '600'), { color: tone.ink, marginTop: 2 }]}>
            {profile.reputation}
          </Text>
        </View>
        <View style={[styles.standing, { backgroundColor: tone.bg }]}>
          <Text style={[t.meta(12, '500', 0), { color: tone.ink }]}>{standing(profile.reputation)}</Text>
        </View>
      </View>
      <Text style={[t.body(14), { color: tone.chalk, marginTop: 8 }]}>
        {parts.length
          ? parts
              .map(
                (part) =>
                  `${part.value} ${part.label}${part.weight > 1 ? ` x${part.weight}` : ''}`,
              )
              .join('  +  ')
          : isMe
            ? 'Earn reputation when you report an issue or confirm one a neighbour reported.'
            : 'Nothing earned yet.'}
      </Text>

      {isMe && (
        <View style={styles.actions}>
          <Pressable
            onPress={report}
            style={({ pressed }) => [styles.action, { backgroundColor: tone.accent, opacity: pressed ? 0.8 : 1 }]}>
            <Camera size={18} color="#000" />
            <Text style={[t.display(15, '600'), { color: '#000', marginLeft: 8 }]}>Report</Text>
          </Pressable>
          <Pressable
            onPress={() => router.dismissTo('/')}
            style={({ pressed }) => [styles.action, { backgroundColor: tone.bg, opacity: pressed ? 0.7 : 1 }]}>
            <Check size={18} color={tone.accentDeep} />
            <Text style={[t.display(15, '600'), { color: tone.ink, marginLeft: 8 }]}>Confirm nearby</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

/** A report's life as three stops, each lit once anything has reached it. */
function Journey({ contributions, isMe }: { contributions: Contributions; isMe: boolean }) {
  const tone = useTone();
  const stops = [
    { label: 'Reported', value: contributions.posts, align: 'flex-start' as const },
    { label: 'Confirmed by', value: contributions.upvotes_received, align: 'center' as const },
    { label: 'Resolved', value: contributions.resolutions, align: 'flex-end' as const },
  ];
  const lit = (i: number) => stops[i].value > 0;

  return (
    <View style={styles.journey}>
      <Text style={[t.body(15), { color: tone.chalk }]}>
        {isMe ? 'Your reports so far' : 'Reports so far'}
      </Text>

      <View style={styles.track}>
        {stops.map((stop, i) => (
          <React.Fragment key={stop.label}>
            <View
              style={[
                styles.node,
                {
                  borderColor: lit(i) ? tone.accent : tone.chalk,
                  backgroundColor: lit(i) ? tone.accent : 'transparent',
                },
              ]}
            />
            {i < stops.length - 1 && (
              <View
                style={[
                  styles.segment,
                  { backgroundColor: lit(i + 1) ? tone.accent : tone.hairline },
                ]}
              />
            )}
          </React.Fragment>
        ))}
      </View>

      <View style={styles.stops}>
        {stops.map((stop) => (
          <View key={stop.label} style={{ flex: 1, alignItems: stop.align }}>
            <Text style={[t.display(30, '600'), { color: tone.ink }]}>{stop.value}</Text>
            <Text style={[t.body(15), { color: tone.chalk, marginTop: 2 }]}>{stop.label}</Text>
          </View>
        ))}
      </View>

      <View style={[styles.rule, { backgroundColor: tone.hairline }]} />

      <Text style={[t.body(15), { color: tone.chalk }]}>Helping neighbours</Text>
      <Text style={[t.display(17, '600'), { color: tone.ink, marginTop: 8 }]}>
        <Text style={{ color: tone.accentDeep }}>{contributions.supports_given} supported</Text>
        <Text style={{ color: tone.chalk }}>{'  ·  '}</Text>
        {contributions.comments_written} {contributions.comments_written === 1 ? 'comment' : 'comments'}
      </Text>
    </View>
  );
}

function emptyText(tab: Tab, isMe: boolean): string {
  if (tab === 1) {
    return isMe
      ? 'Reports you see through to resolved will be collected here.'
      : 'Nothing resolved yet.';
  }
  if (tab === 2) {
    return isMe
      ? 'Reports you independently confirm will be collected here.'
      : 'Nothing supported yet.';
  }
  return isMe
    ? 'Nothing reported yet. Tap plus on the home screen to file the first one.'
    : 'No reports yet.';
}

function Empty({ text }: { text: string }) {
  const tone = useTone();
  return (
    <Text
      style={[
        t.body(14.5),
        { color: tone.chalk, textAlign: 'center', paddingHorizontal: 34, paddingVertical: 44 },
      ]}>
      {text}
    </Text>
  );
}

const styles = StyleSheet.create({
  header: { paddingTop: 10 },
  identity: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: metric.gutter,
  },
  ring: { padding: 3, borderRadius: 999, borderWidth: 2 },
  edit: { paddingHorizontal: 6 },
  score: {
    marginHorizontal: metric.gutter,
    marginTop: 22,
    padding: 18,
    borderRadius: 20,
  },
  scoreHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  standing: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  actions: { flexDirection: 'row', gap: 10, marginTop: 16 },
  action: {
    flex: 1, height: 50, borderRadius: 14,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
  },
  journey: { paddingHorizontal: metric.gutter, paddingTop: 28, paddingBottom: 8 },
  track: { flexDirection: 'row', alignItems: 'center', marginTop: 18, paddingHorizontal: 1 },
  node: { width: 14, height: 14, borderRadius: 7, borderWidth: 2 },
  segment: { flex: 1, height: 2 },
  stops: { flexDirection: 'row', marginTop: 12 },
  rule: { height: StyleSheet.hairlineWidth, marginVertical: 22 },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, marginTop: 18 },
  tab: { flex: 1, alignItems: 'center' },
  indicator: { height: 3, width: 30, borderRadius: 2, marginTop: 8 },
});
