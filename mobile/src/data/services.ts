import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import * as SecureStore from 'expo-secure-store';
import { LocationError, type AuthGateway, type LocationService, type PhotoSource } from './repository';
import type { Tokens } from './client';
import { onTokensChanged, request, setTokens } from './client';
import { registerForPush, unregisterFromPush } from './push';

const TOKEN_KEY = 'fihy.access_token';
const REFRESH_KEY = 'fihy.refresh_token';
const USER_KEY = 'fihy.user_id';

export class ApiAuthGateway implements AuthGateway {
  private userId: string | null = null;

  constructor() {
    // A refresh that replaces the pair has to reach storage, and one that
    // fails has to clear the cached user, or the app keeps rendering as
    // signed in against a session the server has already dropped.
    onTokensChanged(async (next) => {
      if (next) {
        await SecureStore.setItemAsync(TOKEN_KEY, next.access_token);
        await SecureStore.setItemAsync(REFRESH_KEY, next.refresh_token);
        return;
      }
      this.userId = null;
      await SecureStore.deleteItemAsync(TOKEN_KEY);
      await SecureStore.deleteItemAsync(REFRESH_KEY);
      await SecureStore.deleteItemAsync(USER_KEY);
    });
  }

  /** Called once at startup so a returning user is not signed out. */
  async restore() {
    const access = await SecureStore.getItemAsync(TOKEN_KEY);
    if (!access) return;
    // A session stored before refresh tokens were kept has no refresh half.
    // It still works until it expires, and renew() declines without one.
    const refresh = await SecureStore.getItemAsync(REFRESH_KEY);
    setTokens({ access_token: access, refresh_token: refresh ?? '' });
    this.userId = await SecureStore.getItemAsync(USER_KEY);
    // Tokens rotate and permission can be granted in Settings meanwhile.
    if (this.userId) void registerForPush();
  }

  currentUserId() {
    return this.userId;
  }

  async requestOtp(phone: string) {
    await request<void>('/auth/otp/request', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    });
  }

  async verifyOtp(phone: string, code: string) {
    const result = await request<Tokens>('/auth/otp/verify', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    });
    setTokens(result);
    const me = await request<{ id: string }>('/me');
    this.userId = me.id;
    await SecureStore.setItemAsync(USER_KEY, me.id);
    void registerForPush();
  }

  async signOut() {
    await unregisterFromPush();
    setTokens(null);
  }
}

const FIX_TIMEOUT_MS = 10_000;
/** A report placed from a fix this old is still on the right street. */
const LAST_KNOWN_MAX_AGE_MS = 5 * 60_000;

export class DeviceLocationService implements LocationService {
  async current() {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== 'granted') {
      throw new LocationError(
        permission.canAskAgain
          ? 'Location permission is needed to place and find reports.'
          : 'Location access is turned off for fihy. Allow it in Settings to place and find reports.',
        permission.canAskAgain ? 'denied' : 'blocked',
      );
    }
    if (!(await Location.hasServicesEnabledAsync())) {
      throw new LocationError(
        'Location services are off. Turn them on to place and find reports.',
        'disabled',
      );
    }

    const position = await this.fix().catch(() => null);
    if (position) return position;

    // A cold GPS indoors can fail outright (kCLErrorLocationUnknown), while a
    // recent fix from any app is still sitting in the OS cache.
    const cached = await Location.getLastKnownPositionAsync({ maxAge: LAST_KNOWN_MAX_AGE_MS }).catch(
      () => null,
    );
    if (cached) return { latitude: cached.coords.latitude, longitude: cached.coords.longitude };

    throw new LocationError(
      "Couldn't find your location. Move somewhere with a clearer view of the sky and try again.",
      'unavailable',
    );
  }

  private async fix() {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<null>((resolve) => {
      timer = setTimeout(() => resolve(null), FIX_TIMEOUT_MS);
    });
    try {
      const position = await Promise.race([
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
        timeout,
      ]);
      return position && { latitude: position.coords.latitude, longitude: position.coords.longitude };
    } finally {
      clearTimeout(timer);
    }
  }
}

/**
 * Re-encodes the picked image before it leaves the device, which drops EXIF
 * (including GPS and device model). The backend re-strips too; this is defence
 * in depth, not a substitute.
 */
export async function sanitize(uri: string): Promise<string> {
  const result = await ImageManipulator.manipulateAsync(
    uri,
    [{ resize: { width: 1920 } }],
    { compress: 0.82, format: ImageManipulator.SaveFormat.JPEG },
  );
  return result.uri;
}

export class CameraPhotoSource implements PhotoSource {
  /** 'library' is a simulator affordance and is gated on __DEV__ by the
   *  caller; a shipped build always takes the camera path. */
  constructor(private source: 'camera' | 'library' = 'camera') {}

  async capture() {
    const permission =
      this.source === 'camera'
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      throw new Error(
        this.source === 'camera'
          ? 'Camera access is needed. Evidence has to be photographed here, not chosen from your library.'
          : 'Photo access is needed to attach evidence.',
      );
    }
    const picker =
      this.source === 'camera'
        ? ImagePicker.launchCameraAsync
        : ImagePicker.launchImageLibraryAsync;
    const result = await picker({ quality: 0.9, exif: false });
    if (result.canceled) return null;
    return sanitize(result.assets[0].uri);
  }

  async pickAvatar() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      throw new Error('Photo access is needed to choose a picture.');
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      quality: 0.9,
      exif: false,
    });
    if (result.canceled) return null;
    return sanitize(result.assets[0].uri);
  }
}
