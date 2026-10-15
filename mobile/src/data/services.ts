import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import * as SecureStore from 'expo-secure-store';
import { LocationError, type AuthGateway, type LocationService, type PhotoSource } from './repository';
import type { GeoPoint } from '../domain/issue';
import type { Tokens } from './client';
import { onTokensChanged, request, setTokens } from './client';
import { registerForPush, unregisterFromPush } from './push';

const TOKEN_KEY = 'fihy.access_token';
const REFRESH_KEY = 'fihy.refresh_token';
const USER_KEY = 'fihy.user_id';

/**
 * The one switch between the two ways a code reaches a phone. Firebase sends a
 * real SMS; 'otp' is the backend's own endpoint, which only logs the code and
 * is what a local backend without FIREBASE_PROJECT_ID can answer. A release
 * build defaults to Firebase and a dev build to the backend.
 */
export const SIGN_IN: 'firebase' | 'otp' =
  (process.env.EXPO_PUBLIC_SIGN_IN as 'firebase' | 'otp' | undefined) ?? (__DEV__ ? 'otp' : 'firebase');

type FirebaseAuth = typeof import('@react-native-firebase/auth');
type Confirmation = Awaited<ReturnType<FirebaseAuth['signInWithPhoneNumber']>>;

const FIREBASE_MESSAGES: Record<string, string> = {
  'auth/invalid-phone-number': 'That phone number does not look right.',
  'auth/invalid-verification-code': 'That code is not right. Check the SMS and try again.',
  'auth/code-expired': 'That code has expired. Go back and send a new one.',
  'auth/session-expired': 'That code has expired. Go back and send a new one.',
  'auth/too-many-requests': 'Too many attempts. Wait a while before trying again.',
  'auth/quota-exceeded': 'Codes cannot be sent right now. Try again later.',
  'auth/network-request-failed': 'No connection. Check your network and try again.',
};

const firebaseError = (error: unknown) => {
  const code = (error as { code?: string } | null)?.code;
  if (code && FIREBASE_MESSAGES[code]) return new Error(FIREBASE_MESSAGES[code]);
  return new Error(`Signing in did not work. Try again.${code ? ` (${code})` : ''}`);
};

export class ApiAuthGateway implements AuthGateway {
  private userId: string | null = null;
  private pending: { phone: string; confirmation: Confirmation } | null = null;

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
    if (SIGN_IN === 'firebase') return this.sendFirebaseCode(phone);
    await request<void>('/auth/otp/request', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    });
  }

  async verifyOtp(phone: string, code: string) {
    const result =
      SIGN_IN === 'firebase'
        ? await request<Tokens>('/auth/firebase', {
            method: 'POST',
            body: JSON.stringify({ id_token: await this.firebaseIdToken(phone, code) }),
          })
        : await request<Tokens>('/auth/otp/verify', {
            method: 'POST',
            body: JSON.stringify({ phone, code }),
          });
    this.pending = null;
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

  // Imported on use so the OTP path never touches the native module, which a
  // build made before Firebase was added does not have.
  private async sendFirebaseCode(phone: string) {
    const { getAuth, signInWithPhoneNumber } = await import('@react-native-firebase/auth');
    try {
      this.pending = { phone, confirmation: await signInWithPhoneNumber(getAuth(), phone) };
    } catch (error) {
      throw firebaseError(error);
    }
  }

  /**
   * Firebase's own session is dropped as soon as its ID token is read: ours is
   * the one the app runs on, and a second session left in the keychain would
   * outlive signing out here.
   */
  private async firebaseIdToken(phone: string, code: string) {
    const { getAuth, getIdToken, signOut } = await import('@react-native-firebase/auth');
    const auth = getAuth();
    try {
      // Android can verify the SMS on its own and sign in before the code is
      // typed, after which confirming it again is rejected.
      let user = auth.currentUser?.phoneNumber === phone ? auth.currentUser : null;
      if (!user) {
        if (this.pending?.phone !== phone) throw { code: 'auth/session-expired' };
        user = (await this.pending.confirmation.confirm(code))?.user ?? auth.currentUser;
      }
      if (!user) throw { code: 'auth/session-expired' };
      return await getIdToken(user);
    } catch (error) {
      throw firebaseError(error);
    } finally {
      await signOut(auth).catch(() => {});
    }
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
          : 'Location access is turned off for Uthao. Allow it in Settings to place and find reports.',
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

  async describe(point: GeoPoint) {
    try {
      const [place] = await Location.reverseGeocodeAsync(point);
      if (!place) return null;
      const street = place.street ?? place.name;
      const area = place.district ?? place.subregion ?? place.city;
      const line = [street, area].filter(Boolean).join(', ');
      return line || null;
    } catch {
      return null;
    }
  }

  async locality(point: GeoPoint) {
    try {
      const [place] = await Location.reverseGeocodeAsync(point);
      if (!place) return null;
      const area = place.district ?? place.subregion ?? place.name;
      const city = place.city ?? place.region;
      const parts = [area, city].filter((part, i, all): part is string => !!part && all.indexOf(part) === i);
      return parts.join(', ') || null;
    } catch {
      return null;
    }
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
