import { useRouter } from 'expo-router';
import React, { useCallback, useMemo } from 'react';
import { ActivityIndicator, Animated, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useConfirm, useNearbyFeed } from '../../data/queries';
import { useServices } from '../../data/context';
import type { GeoPoint, Issue } from '../../domain/issue';
import { metric, type as t, useTone } from '../../theme/tokens';
import { useChromeOnScroll, useChromeSpacing } from '../shell/chrome';
import { IssueCard } from './IssueCard';


/** Native-driven onScroll needs an explicitly animated list. */
const ScrollList = Animated.createAnimatedComponent(
  FlatList,
) as unknown as typeof FlatList;

export function NearbyFeed({ point }: { point: GeoPoint }) {
  const tone = useTone();
  const router = useRouter();
  const { auth } = useServices();
  const confirm = useConfirm();
  const feed = useNearbyFeed(point);
  const chrome = useChromeOnScroll();
  const spacing = useChromeSpacing(96);

  const issues = useMemo(
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

  if (feed.isPending) return <Centered><ActivityIndicator color={tone.accentDeep} /></Centered>;
  if (feed.isError) return <Notice text={`Could not load issues: ${(feed.error as Error).message}`} />;
  if (!issues.length) {
    return <Notice text="Nothing reported near you yet. Tap plus to be the first." />;
  }

  return (
    <ScrollList
      data={issues}
      keyExtractor={(issue) => issue.id}
      {...chrome}
      contentContainerStyle={spacing}
      onEndReachedThreshold={0.6}
      onEndReached={() => feed.hasNextPage && !feed.isFetchingNextPage && feed.fetchNextPage()}
      refreshControl={
        <RefreshControl
          refreshing={feed.isRefetching}
          onRefresh={feed.refetch}
          tintColor={tone.accentDeep}
          progressViewOffset={spacing.paddingTop}
        />
      }
      ListFooterComponent={
        feed.isFetchingNextPage ? (
          <View style={{ paddingVertical: 26 }}>
            <ActivityIndicator color={tone.accentDeep} />
          </View>
        ) : null
      }
      renderItem={({ item }) => (
        <IssueCard
          issue={item}
          onPress={() => router.push(`/issues/${item.id}`)}
          onConfirm={() => onConfirm(item)}
        />
      )}
    />
  );
}

export const Centered = ({ children }: { children: React.ReactNode }) => (
  <View style={styles.centered}>{children}</View>
);

export function Notice({ text }: { text: string }) {
  const tone = useTone();
  return (
    <View style={styles.centered}>
      <Text style={[t.body(15), { color: tone.chalk, textAlign: 'center', padding: 28 }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: metric.gutter },
});
