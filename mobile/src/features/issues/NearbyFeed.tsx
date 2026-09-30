import { useRouter } from 'expo-router';
import { LocateOff, MapPinOff, WifiOff, type LucideIcon } from 'lucide-react-native';
import React, { useCallback, useMemo } from 'react';
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Linking,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { isOffline } from '../../data/client';
import { useConfirm, useFeed } from '../../data/queries';
import { LocationError } from '../../data/repository';
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
  const feed = useFeed(point);
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
  if (feed.isError) return <LoadFailed error={feed.error} onRetry={feed.refetch} />;
  if (!issues.length) {
    return (
      <Notice
        icon={MapPinOff}
        title="No reports nearby"
        text="Nothing has been reported around you yet. Tap plus to be the first."
        action="Refresh"
        onAction={feed.refetch}
      />
    );
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

export function Notice({
  text,
  title,
  icon: Icon,
  action,
  onAction,
}: {
  text: string;
  title?: string;
  icon?: LucideIcon;
  action?: string;
  onAction?: () => void;
}) {
  const tone = useTone();
  return (
    <View style={styles.centered}>
      {Icon && <Icon size={30} strokeWidth={1.6} color={tone.chalk} style={{ marginBottom: 14 }} />}
      {title && (
        <Text style={[t.display(18, '700'), { color: tone.ink, textAlign: 'center' }]}>{title}</Text>
      )}
      <Text
        style={[
          t.body(15),
          { color: tone.chalk, textAlign: 'center', paddingHorizontal: 28, paddingTop: title ? 6 : 28, paddingBottom: 28 },
        ]}>
        {text}
      </Text>
      {action && onAction && (
        <Pressable
          onPress={onAction}
          style={({ pressed }) => [styles.action, { borderColor: tone.hairline, opacity: pressed ? 0.6 : 1 }]}>
          <Text style={[t.meta(12, '700', 0.2), { color: tone.ink }]}>{action}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function LoadFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const offline = isOffline(error);
  return (
    <Notice
      icon={offline ? WifiOff : undefined}
      title={offline ? 'Can\'t connect' : 'Could not load issues'}
      text={(error as Error).message}
      action="Try again"
      onAction={onRetry}
    />
  );
}

/** Coming back from Settings refocuses the app, which refetches the failed
 *  location query on its own, so the button only has to get them there. */
export function LocationFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const reason = error instanceof LocationError ? error.reason : 'unavailable';
  const blocked = reason === 'blocked';
  return (
    <Notice
      icon={LocateOff}
      title={reason === 'denied' || blocked ? 'Location is off' : 'Location unavailable'}
      text={(error as Error).message}
      action={blocked ? 'Open Settings' : 'Try again'}
      onAction={blocked ? () => Linking.openSettings() : onRetry}
    />
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: metric.gutter },
  action: {
    height: 38, paddingHorizontal: 22, marginTop: -12,
    borderWidth: 1, borderRadius: metric.radius,
    alignItems: 'center', justifyContent: 'center',
  },
});
