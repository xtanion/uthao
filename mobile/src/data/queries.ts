import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Category, GeoPoint, Severity, Status, SupportDraft } from '../domain/issue';
import type { Period, StatsScope } from '../domain/stats';
import { useServices } from './context';
import { SEARCH_RADIUS_M } from './repository';

const key = (point: GeoPoint) => ['nearby', point.latitude, point.longitude] as const;

/** The repository's opaque cursor maps straight onto useInfiniteQuery. */
export function useNearbyFeed(point: GeoPoint) {
  const { issues } = useServices();
  return useInfiniteQuery({
    queryKey: key(point),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => issues.nearby({ point, cursor: pageParam }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

/** The home feed. Ranked server-side, and never empty when anything exists. */
export function useFeed(point: GeoPoint) {
  const { issues } = useServices();
  return useInfiniteQuery({
    queryKey: ['feed', point.latitude, point.longitude],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => issues.feed(point, pageParam),
    getNextPageParam: (last) => last.next_cursor,
    // The feed does not refresh under somebody who is reading it. Reordering a
    // list while a person is halfway down it loses their place and can swap
    // the card out from under a tap, and none of the reasons to refetch are
    // worth that. It reloads when they ask for it: a pull, their own support
    // or report, or coming back to a screen that had been left.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useMapIssues(point: GeoPoint) {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['map', point.latitude, point.longitude],
    queryFn: () => issues.nearby({ point, limit: 200 }),
  });
}

export function useIssue(id: string) {
  const { issues } = useServices();
  return useQuery({ queryKey: ['issue', id], queryFn: () => issues.get(id) });
}

export function useLocation() {
  const { location } = useServices();
  return useQuery({ queryKey: ['location'], queryFn: () => location.current(), retry: false });
}

export function useConfirm() {
  const { issues } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, confirmed }: { id: string; confirmed: boolean }) =>
      confirmed ? issues.unconfirm(id) : issues.confirm(id),
    onSuccess: (updated) => {
      client.setQueryData(['issue', updated.id], updated);
      client.invalidateQueries({ queryKey: ['nearby'] });
      client.invalidateQueries({ queryKey: ['feed'] });
      client.invalidateQueries({ queryKey: ['search'] });
      client.invalidateQueries({ queryKey: ['mine'] });
      // A confirmation moves both profiles: the reporter's score and the
      // supporter's own Supports tab.
      client.invalidateQueries({ queryKey: ['profile'] });
      client.invalidateQueries({ queryKey: ['supports'] });
    },
  });
}

export function useSupports(issueId: string) {
  const { issues } = useServices();
  return useInfiniteQuery({
    queryKey: ['supports', issueId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => issues.supports(issueId, pageParam),
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useGallery(issueId: string) {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['gallery', issueId],
    queryFn: () => issues.photos(issueId),
  });
}

/** Adding words or a photo changes the issue, the thread, and the gallery, so
 *  all three are refreshed rather than patched. */
export function useSupport(issueId: string) {
  const { issues } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: SupportDraft) => issues.support(issueId, draft),
    onSuccess: (updated) => {
      client.setQueryData(['issue', updated.id], updated);
      for (const key of [['supports', issueId], ['gallery', issueId], ['issue', issueId]]) {
        client.invalidateQueries({ queryKey: key });
      }
      client.invalidateQueries({ queryKey: ['nearby'] });
      client.invalidateQueries({ queryKey: ['feed'] });
    },
  });
}

/** Withdrawing takes the photos that came with the support, so the gallery is
 *  refreshed alongside the thread. */
export function useWithdrawSupport(issueId: string) {
  const { issues } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => issues.withdrawSupport(issueId),
    onSuccess: (updated) => {
      client.setQueryData(['issue', updated.id], updated);
      for (const key of [['supports', issueId], ['gallery', issueId]]) {
        client.invalidateQueries({ queryKey: key });
      }
      client.invalidateQueries({ queryKey: ['nearby'] });
      client.invalidateQueries({ queryKey: ['feed'] });
      client.invalidateQueries({ queryKey: ['mine'] });
    },
  });
}

/** Only fetched once the window is open: before that there is nothing on the
 *  board and the track already says when it opens. */
export function useFixDates(issueId: string, enabled: boolean) {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['fix-dates', issueId],
    queryFn: () => issues.fixDates(issueId),
    enabled,
  });
}

/** Every write returns the whole board, so the cache is replaced rather than
 *  invalidated and the poll never flickers back to its old counts. */
export function useProposeFixDate(issueId: string) {
  const { issues } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fixOn, fixTime }: { fixOn: string; fixTime?: string | null }) =>
      issues.proposeFixDate(issueId, fixOn, fixTime),
    onSuccess: (board) => client.setQueryData(['fix-dates', issueId], board),
  });
}

export function useVoteFixDate(issueId: string) {
  const { issues } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) =>
      issues.voteFixDate(issueId, id, on),
    onSuccess: (board) => client.setQueryData(['fix-dates', issueId], board),
  });
}

export type SearchFilters = {
  q: string;
  category?: Category;
  severity?: Severity;
};

/** Enabled only once there is something to search for, so opening the screen
 *  does not fire a query for every issue in range. */
export function useSearch(point: GeoPoint, filters: SearchFilters) {
  const { issues } = useServices();
  const q = filters.q.trim();
  const active = q.length > 0 || Boolean(filters.category) || Boolean(filters.severity);
  return useInfiniteQuery({
    queryKey: ['search', point.latitude, point.longitude, q, filters.category ?? null, filters.severity ?? null],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      issues.nearby({
        point,
        radiusM: SEARCH_RADIUS_M,
        q,
        category: filters.category,
        severity: filters.severity,
        cursor: pageParam,
      }),
    getNextPageParam: (last) => last.next_cursor,
    enabled: active,
  });
}

export function useMyIssues(enabled: boolean) {
  const { issues } = useServices();
  return useInfiniteQuery({
    queryKey: ['mine'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => issues.mine(pageParam),
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

export function useNotifications(enabled: boolean) {
  const { notifications } = useServices();
  return useInfiniteQuery({
    queryKey: ['notifications'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => notifications.list(pageParam),
    getNextPageParam: (last) => last.next_cursor,
    enabled,
    // A push invalidates this as it arrives, so polling is only the fallback
    // for a phone that declined notifications. Paused while backgrounded.
    refetchInterval: 5 * 60_000,
  });
}

/** The unread count lives on every page, so the badge reads the first one. */
export function useUnreadCount(enabled: boolean) {
  const feed = useNotifications(enabled);
  return feed.data?.pages[0]?.unread_count ?? 0;
}

export function useMarkNotificationsRead() {
  const { notifications } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids?: string[]) => notifications.markRead(ids),
    onSuccess: () => client.invalidateQueries({ queryKey: ['notifications'] }),
  });
}

export function useProfile(userId: string | null) {
  const { users } = useServices();
  return useQuery({
    queryKey: ['profile', userId],
    queryFn: () => users.profile(userId as string),
    enabled: Boolean(userId),
  });
}

export function useEscalation(issueId: string) {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['escalation', issueId],
    queryFn: () => issues.escalation(issueId),
  });
}

/** Account edits refresh both the profile and the masthead read of /me. */
function useAccountMutation<T>(run: (value: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['profile'] });
      client.invalidateQueries({ queryKey: ['userIssues'] });
    },
  });
}

export function useUpdateName() {
  const { users } = useServices();
  return useAccountMutation((name: string) => users.updateName(name));
}

export function useSetAvatar() {
  const { users } = useServices();
  return useAccountMutation((uri: string) => users.setAvatar(uri));
}

export function useClearAvatar() {
  const { users } = useServices();
  return useAccountMutation((_: void) => users.clearAvatar());
}

export function useSignOut() {
  const { auth } = useServices();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => auth.signOut(),
    // Everything cached was read as that person; none of it survives them.
    onSuccess: () => client.clear(),
  });
}

export function useUserIssues(userId: string | null, status?: Status) {
  const { users } = useServices();
  return useInfiniteQuery({
    queryKey: ['userIssues', userId, status ?? null],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => users.issues(userId as string, pageParam, status),
    getNextPageParam: (last) => last.next_cursor,
    enabled: Boolean(userId),
  });
}

export function useUserSupports(userId: string | null) {
  const { users } = useServices();
  return useInfiniteQuery({
    queryKey: ['supports', userId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => users.supports(userId as string, pageParam),
    getNextPageParam: (last) => last.next_cursor,
    enabled: Boolean(userId),
  });
}

/** Rounded so a GPS fix drifting a few metres does not refetch the page. */
const scopeKey = ({ area, point }: StatsScope) =>
  area
    ? [area]
    : point
      ? [Number(point.latitude.toFixed(2)), Number(point.longitude.toFixed(2))]
      : [null];

export function useStats(scope: StatsScope, enabled: boolean) {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['stats', 'page', ...scopeKey(scope)],
    queryFn: () => issues.stats(scope),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useStatsAreas() {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['stats', 'areas'],
    queryFn: () => issues.statsAreas(),
    staleTime: 30 * 60_000,
  });
}

export function useTopContributors(period: Period, scope: StatsScope) {
  const { issues } = useServices();
  return useQuery({
    queryKey: ['stats', 'contributors', period, ...scopeKey(scope)],
    queryFn: () => issues.topContributors(period, scope),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}
