import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect } from 'react';

/**
 * The last good copy of a few screens (feed, profiles), kept on disk so a cold
 * start opens on something instead of a spinner. Shown as placeholder data
 * while the real request runs, and replaced the moment it lands.
 *
 * Read once at launch into memory, so a screen can pick its snapshot up on its
 * first render without waiting on storage.
 */
const PREFIX = 'uthao.snapshot.';
const memory = new Map<string, unknown>();

/** Keeps the disk copy small: a feed is one page, not a whole scroll. */
type Trim<T> = (data: T) => T;

export async function hydrateSnapshots(): Promise<void> {
  try {
    const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith(PREFIX));
    for (const [k, v] of await AsyncStorage.multiGet(keys)) {
      if (v) memory.set(k.slice(PREFIX.length), JSON.parse(v));
    }
  } catch {
    // No snapshot just means a spinner, like before.
  }
}

export function readSnapshot<T>(key: string): T | undefined {
  return memory.get(key) as T | undefined;
}

export function writeSnapshot<T>(key: string, data: T): void {
  memory.set(key, data);
  AsyncStorage.setItem(PREFIX + key, JSON.stringify(data)).catch(() => {});
}

/** Everything cached was read as that person; none of it survives sign-out. */
export async function clearSnapshots(): Promise<void> {
  memory.clear();
  try {
    const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith(PREFIX));
    await AsyncStorage.multiRemove(keys);
  } catch {}
}

/** Saves fresh data (never the placeholder itself) under `key`. */
export function useSaveSnapshot<T>(
  key: string | null,
  query: { data: T | undefined; isPlaceholderData: boolean; isSuccess: boolean },
  trim?: Trim<T>,
) {
  const { data, isPlaceholderData, isSuccess } = query;
  useEffect(() => {
    if (!key || !isSuccess || isPlaceholderData || data === undefined) return;
    writeSnapshot(key, trim ? trim(data) : data);
    // trim is a stable helper; leaving it out keeps callers from memoising it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, data, isPlaceholderData, isSuccess]);
}

/** First page only, so the snapshot is one screen's worth. */
export const firstPage = <P,>(data: { pages: P[]; pageParams: unknown[] }) => ({
  pages: data.pages.slice(0, 1),
  pageParams: data.pageParams.slice(0, 1),
});
