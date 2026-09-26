import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Category, GeoPoint, Severity, Status, SupportDraft } from '../domain/issue';
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
  const { issues, location } = useServices();
  const client = useQueryClient();
  return useMutation({
    // Photos only count from where the problem is, so they go with a fresh fix
    // rather than wherever the app was when it opened. Words go without.
    mutationFn: async (draft: SupportDraft) =>
      issues.support(
        issueId,
        draft.photos.length && !draft.location
          ? { ...draft, location: await location.current() }
          : draft,
      ),
    onSuccess: (updated) => {
      client.setQueryData(['issue', updated.id], updated);
      for (const key of [['supports', issueId], ['gallery', issueId], ['issue', issueId]]) {
        client.invalidateQueries({ queryKey: key });
      }
      client.invalidateQueries({ queryKey: ['nearby'] });
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
