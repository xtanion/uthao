import { Image } from 'expo-image';
import React from 'react';
import type { ImageStyle, StyleProp } from 'react-native';

/**
 * A server photo or avatar, cached on disk by what it is rather than by its
 * link.
 *
 * Every link the server hands out is signed and expires after a few minutes,
 * so the query string changes on every fetch. Caching by the full URL would
 * miss every time, and a cached screen opened after expiry would show blanks.
 * The path (the object key) never changes, so it is the cache key: once a
 * photo has been seen it shows instantly, signed link or not.
 */
const stableKey = (uri: string) => uri.split('?')[0];

const FIT = { cover: 'cover', contain: 'contain', stretch: 'fill', center: 'none' } as const;

export function RemoteImage({
  source,
  style,
  resizeMode = 'cover',
}: {
  source: { uri: string };
  style?: StyleProp<ImageStyle>;
  resizeMode?: keyof typeof FIT;
}) {
  return (
    <Image
      source={{ uri: source.uri, cacheKey: stableKey(source.uri) }}
      style={style}
      contentFit={FIT[resizeMode]}
      cachePolicy="disk"
      transition={120}
    />
  );
}
