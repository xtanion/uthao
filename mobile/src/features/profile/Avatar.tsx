import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { RemoteImage } from '../shell/RemoteImage';
import Svg, { Line } from 'react-native-svg';
import { initials } from '../../domain/profile';

const PALETTE = [
  '#e4572e', '#f3a712', '#29335c', '#0fc47c', '#3a86ff', '#8e6c8a',
  '#2d6a4f', '#ffb4a2', '#ffd60a', '#7209b7', '#118ab2', '#ef476f',
];

const GRID_CELLS = 8;

const seed = (id: string) => {
  let total = 0;
  for (let i = 0; i < id.length; i += 1) total = (total * 31 + id.charCodeAt(i)) >>> 0;
  return total;
};

const inkOn = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  const luminance = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  return luminance > 0.6 ? '#101014' : '#ffffff';
};

export function Avatar({
  id,
  name,
  uri,
  size = 64,
}: {
  id: string;
  name: string;
  uri?: string | null;
  size?: number;
}) {
  const radius = size / 2;

  if (uri) {
    return (
      <RemoteImage
        source={{ uri }}
        style={{ width: size, height: size, borderRadius: radius }}
        resizeMode="cover"
      />
    );
  }

  const fill = PALETTE[seed(id) % PALETTE.length];
  const ink = inkOn(fill);
  const fontSize = size * 0.4;
  const cell = size / GRID_CELLS;
  const lines = Array.from({ length: GRID_CELLS - 1 }, (_, i) => (i + 1) * cell);

  return (
    <View style={{ width: size, height: size, borderRadius: radius, overflow: 'hidden', backgroundColor: fill }}>
      <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
        {lines.map((at) => (
          <React.Fragment key={at}>
            <Line x1={at} x2={at} y1={0} y2={size} stroke={ink} strokeOpacity={0.14} strokeWidth={Math.max(size / 128, 0.5)} />
            <Line x1={0} x2={size} y1={at} y2={at} stroke={ink} strokeOpacity={0.14} strokeWidth={Math.max(size / 128, 0.5)} />
          </React.Fragment>
        ))}
      </Svg>
      <View style={styles.center}>
        <Text
          allowFontScaling={false}
          numberOfLines={1}
          adjustsFontSizeToFit
          minimumFontScale={0.5}
          style={{
            width: size * 0.8,
            fontFamily: 'GeistPixel-Square',
            fontSize,
            lineHeight: fontSize * 1.25,
            textAlign: 'center',
            includeFontPadding: false,
            color: ink,
          }}>
          {initials(name)}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center' },
});
