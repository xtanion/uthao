import { useRouter } from 'expo-router';
import React, { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
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
import { REPUTATION_WEIGHTS, joinedLabel } from '../../domain/profile';
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
          <Header profile={profile.data} isMe={isMe} />
          <View style={[styles.tabs, { borderBottomColor: tone.hairline }]}>
            {TABS.map((label, i) => (
              <Pressable key={label} style={styles.tab} onPress={() => setTab(i as Tab)}>
                <Text
                  style={[
                    t.display(14, '700'),
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

/** Name and score lead; the avatar sits opposite, as on Threads. */
function Header({ profile, isMe }: { profile: Profile; isMe: boolean }) {
  const tone = useTone();
  const router = useRouter();
  const joined = joinedLabel(profile.joined_at);
  return (
    <View style={styles.header}>
      <View style={styles.identity}>
        <View style={{ flex: 1, paddingRight: 14 }}>
          <Text style={[t.display(26, '700'), { color: tone.ink }]}>
            {profile.display_name}
          </Text>
          <Text style={[t.meta(11, '500', 0.4), { color: tone.chalk, marginTop: 5 }]}>
            {isMe ? 'You' : 'Hooman'}
            {joined ? `  ·  Joined ${joined}` : ''}
          </Text>
        </View>
        <Avatar
          id={profile.id}
          name={profile.display_name}
          uri={profile.avatar_url}
          size={66}
        />
      </View>

      {isMe && (
        <Pressable
          onPress={() => router.push('/profile/edit')}
          style={[styles.edit, { borderColor: tone.hairline }]}>
          <Text style={[t.meta(12, '700', 0.2), { color: tone.ink }]}>Edit profile</Text>
        </Pressable>
      )}

      <Reputation profile={profile} />
      <ContributionGrid contributions={profile.contributions} />
    </View>
  );
}

/**
 * The score with its own arithmetic printed underneath. A number nobody can
 * account for invites suspicion; this one shows its work, the same reason the
 * issue detail spells out its corroboration count.
 */
function Reputation({ profile }: { profile: Profile }) {
  const tone = useTone();
  const { upvotes_received, posts, resolutions } = profile.contributions;
  const parts = [
    { value: upvotes_received, weight: REPUTATION_WEIGHTS.upvote, label: 'confirmations' },
    { value: posts, weight: REPUTATION_WEIGHTS.post, label: 'reports' },
    { value: resolutions, weight: REPUTATION_WEIGHTS.resolution, label: 'resolved' },
  ].filter((part) => part.value > 0);

  return (
    <View style={[styles.score, { borderColor: tone.hairline }]}>
      <View style={styles.scoreRow}>
        <Text style={[t.display(34, '700'), { color: tone.ink }]}>
          {profile.reputation}
        </Text>
        <Text style={[t.meta(11, '700', 0), { color: tone.chalk, marginLeft: 9 }]}>
          Reputation
        </Text>
      </View>
      <Text style={[t.body(13), { color: tone.chalk, marginTop: 4 }]}>
        {parts.length
          ? parts
              .map(
                (part) =>
                  `${part.value} ${part.label}${part.weight > 1 ? ` x${part.weight}` : ''}`,
              )
              .join('  +  ')
          : 'Report something or confirm a neighbour to start earning.'}
      </Text>
    </View>
  );
}

const ORDER: (keyof Contributions)[] = [
  'posts',
  'upvotes_received',
  'supports_given',
  'resolutions',
  'comments_written',
];

const SHORT: Record<keyof Contributions, string> = {
  posts: 'Reports',
  upvotes_received: 'Confirmed by',
  supports_given: 'Supported',
  resolutions: 'Resolved',
  comments_written: 'Comments',
};

function ContributionGrid({ contributions }: { contributions: Contributions }) {
  const tone = useTone();
  return (
    <View style={styles.stats}>
      {ORDER.map((key) => (
        <View key={key} style={[styles.stat, { borderColor: tone.hairline }]}>
          <Text style={[t.display(19, '700'), { color: tone.ink }]}>
            {contributions[key]}
          </Text>
          <Text style={[t.meta(11, '500', 0), { color: tone.chalk, marginTop: 3 }]}>
            {SHORT[key]}
          </Text>
        </View>
      ))}
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
  header: { paddingTop: 6 },
  identity: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: metric.gutter,
  },
  score: {
    marginHorizontal: metric.gutter,
    marginTop: 18,
    paddingVertical: 13,
    borderTopWidth: 1,
    borderBottomWidth: 1,
  },
  scoreRow: { flexDirection: 'row', alignItems: 'baseline' },
  edit: {
    marginHorizontal: metric.gutter, marginTop: 16, height: 38,
    borderWidth: 1, borderRadius: metric.radius,
    alignItems: 'center', justifyContent: 'center',
  },
  stats: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    paddingHorizontal: metric.gutter - 4,
    paddingTop: 14,
    paddingBottom: 4,
  },
  stat: {
    width: '33.33%',
    paddingVertical: 9,
    paddingHorizontal: 4,
  },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, marginTop: 10 },
  tab: { flex: 1, alignItems: 'center' },
  indicator: { height: 3, width: 30, borderRadius: 2, marginTop: 8 },
});
