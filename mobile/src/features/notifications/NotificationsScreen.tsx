import { useRouter } from 'expo-router';
import { ArrowUp, CircleX } from 'lucide-react-native';
import React, { useCallback, useMemo } from 'react';
import {
  Animated,
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useServices } from '../../data/context';
import { useMarkNotificationsRead, useNotifications } from '../../data/queries';
import { shortAge } from '../../domain/issue';
import type { Notification } from '../../domain/notification';
import { notificationContext, notificationLine } from '../../domain/notification';
import { metric, type as t, useTone } from '../../theme/tokens';
import { StatusGlyph } from '../issues/glyphs';
import { Centered, Notice } from '../issues/NearbyFeed';
import { useChromeOnScroll, useChromeSpacing } from '../shell/chrome';


/** Native-driven onScroll needs an explicitly animated list. */
const ScrollList = Animated.createAnimatedComponent(
  FlatList,
) as unknown as typeof FlatList;

export function NotificationsScreen() {
  const tone = useTone();
  const router = useRouter();
  const { auth } = useServices();
  const signedIn = Boolean(auth.currentUserId());
  const feed = useNotifications(signedIn);
  const markRead = useMarkNotificationsRead();
  const chrome = useChromeOnScroll();
  const spacing = useChromeSpacing(96);

  const items = useMemo(
    () => feed.data?.pages.flatMap((p) => p.items) ?? [],
    [feed.data],
  );
  const unread = feed.data?.pages[0]?.unread_count ?? 0;

  const open = useCallback(
    (item: Notification) => {
      if (!item.read) markRead.mutate([item.id]);
      router.push(`/issues/${item.issue.id}`);
    },
    [markRead, router],
  );

  if (!signedIn) {
    return (
      <View style={styles.gate}>
        <Text style={[t.body(15), { color: tone.chalk, textAlign: 'center' }]}>
          Sign in to see when neighbours confirm your reports.
        </Text>
        <Pressable
          onPress={() => router.push('/auth')}
          style={[styles.cta, { backgroundColor: tone.accent }]}>
          <Text style={[t.display(16, '600'), { color: '#000' }]}>Sign in</Text>
        </Pressable>
      </View>
    );
  }

  if (feed.isPending) {
    return (
      <Centered>
        <ActivityIndicator color={tone.accentDeep} />
      </Centered>
    );
  }
  if (feed.isError) return <Notice text={(feed.error as Error).message} />;
  if (!items.length) {
    return (
      <Notice text="Nothing yet. When someone independently confirms one of your reports, it shows up here." />
    );
  }

  return (
    <ScrollList
      data={items}
      keyExtractor={(item) => item.id}
      {...chrome}
      contentContainerStyle={spacing}
      refreshControl={
        <RefreshControl
          refreshing={feed.isRefetching}
          onRefresh={feed.refetch}
          tintColor={tone.accentDeep}
          progressViewOffset={spacing.paddingTop}
        />
      }
      ListHeaderComponent={
        <View style={styles.head}>
          <Text style={[t.meta(11, '600', 0), { color: tone.chalk }]}>
            {unread > 0 ? `${unread} unread` : 'All caught up'}
          </Text>
          <View style={{ flex: 1 }} />
          {unread > 0 && (
            <Pressable onPress={() => markRead.mutate(undefined)} hitSlop={8}>
              <Text style={[t.meta(11, '700', 0.3), { color: tone.accentDeep }]}>
                Mark all read
              </Text>
            </Pressable>
          )}
        </View>
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
      renderItem={({ item }) => <Row item={item} onPress={() => open(item)} />}
    />
  );
}

function Row({ item, onPress }: { item: Notification; onPress: () => void }) {
  const tone = useTone();
  const confirmation = item.type === 'support_received';
  const rejected = item.type === 'support_rejected';
  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.row,
        {
          borderBottomColor: tone.hairline,
          backgroundColor: item.read ? 'transparent' : `${tone.accent}14`,
        },
      ]}>
      <View
        style={[
          styles.badge,
          {
            backgroundColor: confirmation ? `${tone.accent}2e` : tone.surface,
            borderColor: tone.hairline,
          },
        ]}>
        {confirmation ? (
          <ArrowUp size={17} color={tone.accentDeep} />
        ) : rejected ? (
          <CircleX size={17} color={tone.hazard} />
        ) : (
          <StatusGlyph
            status={item.to_status ?? item.issue.status}
            size={17}
            color={tone.ink}
          />
        )}
      </View>

      <View style={styles.body}>
        {/* A rejection carries its reason, which needs room to be read. */}
        <Text numberOfLines={rejected ? 4 : 2} style={[t.display(15, '600'), { color: tone.ink }]}>
          {notificationLine(item)}
        </Text>
        <Text
          numberOfLines={1}
          style={[t.body(13.5), { color: tone.chalk, marginTop: 2 }]}>
          {notificationContext(item)}
        </Text>
      </View>

      <View style={styles.trail}>
        <Text style={[t.meta(11, '500', 0), { color: tone.chalk }]}>
          {shortAge(item.created_at)}
        </Text>
        {!item.read && <View style={[styles.dot, { backgroundColor: tone.accent }]} />}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  gate: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28 },
  cta: {
    height: 48,
    borderRadius: metric.radius,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 34,
    marginTop: 18,
  },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: metric.gutter,
    paddingTop: 14,
    paddingBottom: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: metric.gutter,
    paddingVertical: 13,
    borderBottomWidth: 1,
  },
  badge: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { flex: 1, marginLeft: 12 },
  trail: { alignItems: 'flex-end', marginLeft: 10, minWidth: 34 },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 7 },
});
