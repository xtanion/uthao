import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { request } from './client';

/** Matches CHANNEL_ID on the backend, which names it on every message. */
export const ACTIVITY_CHANNEL = 'activity';

/** Foreground pushes still show, and the badge follows the server's count. */
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

const projectId = (): string | undefined =>
  Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;

/** Expo Go on Android has had no remote push since SDK 53; asking only logs. */
const unsupported = () =>
  Platform.OS === 'android' &&
  Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

let registered: string | null = null;

async function permitted(): Promise<boolean> {
  const current = await Notifications.getPermissionsAsync();
  if (allowed(current)) return true;
  if (!current.canAskAgain) return false;
  return allowed(await Notifications.requestPermissionsAsync());
}

const allowed = (status: Notifications.NotificationPermissionsStatus) =>
  status.granted ||
  status.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL;

/**
 * Best effort throughout: a phone that never registers still has the feed,
 * so nothing here is allowed to fail sign-in or startup.
 */
export async function registerForPush(): Promise<void> {
  if (unsupported()) return;
  const id = projectId();
  if (!id) {
    if (__DEV__) console.warn('[push] no EAS projectId; run `eas init` to enable push');
    return;
  }
  try {
    // Android 13 shows no permission prompt until a channel exists.
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync(ACTIVITY_CHANNEL, {
        name: 'Activity on your reports',
        importance: Notifications.AndroidImportance.HIGH,
      });
    }
    if (!(await permitted())) return;
    const token = (await Notifications.getExpoPushTokenAsync({ projectId: id })).data;
    await request<void>('/me/push-tokens', {
      method: 'PUT',
      body: JSON.stringify({ token, platform: Platform.OS === 'ios' ? 'ios' : 'android' }),
    });
    registered = token;
  } catch (error) {
    if (__DEV__) console.warn('[push] registration failed', error);
  }
}

/** Has to run while the session is still valid, so before tokens are cleared. */
export async function unregisterFromPush(): Promise<void> {
  const token = registered;
  registered = null;
  if (!token) return;
  try {
    await request<void>(`/me/push-tokens/${encodeURIComponent(token)}`, { method: 'DELETE' });
  } catch {
    // The token is moved to whoever signs in next on this phone anyway.
  }
  await Notifications.setBadgeCountAsync(0).catch(() => undefined);
}
