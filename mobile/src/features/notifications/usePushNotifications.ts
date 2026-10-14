import { useQueryClient } from '@tanstack/react-query';
import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';
import { useEffect } from 'react';
import { registerForPush } from '../../data/push';

/**
 * Mounted by the home shell, which is under the navigator by the time it
 * renders, so a tap that cold-started the app can still be routed.
 */
export function usePushNotifications(signedIn: boolean, unread: number) {
  const router = useRouter();
  const client = useQueryClient();
  const response = Notifications.useLastNotificationResponse();

  useEffect(() => {
    if (!response || response.actionIdentifier !== Notifications.DEFAULT_ACTION_IDENTIFIER) return;
    const issueId = response.notification.request.content.data?.issue_id;
    // Cleared first, so a remount of the shell does not open it twice.
    Notifications.clearLastNotificationResponse();
    client.invalidateQueries({ queryKey: ['notifications'] });
    if (typeof issueId === 'string') router.push(`/issues/${issueId}`);
  }, [response, client, router]);

  useEffect(() => {
    const arrived = Notifications.addNotificationReceivedListener((notification) => {
      client.invalidateQueries({ queryKey: ['notifications'] });
      const issueId = notification.request.content.data?.issue_id;
      if (typeof issueId === 'string') client.invalidateQueries({ queryKey: ['issue', issueId] });
    });
    return () => arrived.remove();
  }, [client]);

  // A rotated device token invalidates the Expo token registered with it.
  useEffect(() => {
    if (!signedIn) return;
    const rotated = Notifications.addPushTokenListener(() => void registerForPush());
    return () => rotated.remove();
  }, [signedIn]);

  // The push carries a badge, but reading the feed here is what clears it.
  useEffect(() => {
    Notifications.setBadgeCountAsync(signedIn ? unread : 0).catch(() => undefined);
  }, [signedIn, unread]);
}
