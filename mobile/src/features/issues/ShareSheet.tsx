import * as Sharing from 'expo-sharing';
import { X } from 'lucide-react-native';
import React, { useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { captureRef } from 'react-native-view-shot';
import type { Issue } from '../../domain/issue';
import type { Poster } from '../../domain/poster';
import { type as t, useTone } from '../../theme/tokens';
import { POSTER_HEIGHT, POSTER_WIDTH, SharePoster } from './SharePoster';
import { shareIssue } from './share';

/**
 * Shows the poster for this report and shares it as an image.
 *
 * The poster renders at its fixed size and is scaled down to fit the preview;
 * the capture is of the poster itself, so the image is always 1080 × 1920
 * whatever the phone. If capturing or the image share fails, the old text
 * share still goes out, so the button never does nothing.
 */
export function ShareSheet({
  issue,
  poster,
  visible,
  onClose,
}: {
  issue: Issue;
  poster: Poster;
  visible: boolean;
  onClose: () => void;
}) {
  const tone = useTone();
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const posterRef = useRef<View>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  // As big as fits between the close button and the share button.
  const room = Math.min(width - 48, ((height - insets.top - insets.bottom - 170) * POSTER_WIDTH) / POSTER_HEIGHT);
  const scale = Math.max(0.4, room / POSTER_WIDTH);

  const share = async () => {
    setBusy(true);
    try {
      const uri = await captureRef(posterRef, {
        format: 'png',
        quality: 1,
        result: 'tmpfile',
        width: POSTER_WIDTH * 3,
        height: POSTER_HEIGHT * 3,
      });
      if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing unavailable');
      await Sharing.shareAsync(uri, {
        mimeType: 'image/png',
        UTI: 'public.png',
        dialogTitle: issue.title,
      });
      onClose();
    } catch {
      await shareIssue(issue);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.sheet, { backgroundColor: tone.bg, paddingBottom: insets.bottom + 16 }]}>
        <View style={styles.head}>
          <Text style={[t.display(17, '700'), { color: tone.ink }]}>Share this report</Text>
          <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button" accessibilityLabel="Close">
            <X size={22} color={tone.ink} />
          </Pressable>
        </View>

        <View style={styles.stage}>
          <View
            style={{
              width: POSTER_WIDTH * scale,
              height: POSTER_HEIGHT * scale,
              borderRadius: 14,
              overflow: 'hidden',
            }}>
            <View
              style={{
                width: POSTER_WIDTH,
                height: POSTER_HEIGHT,
                transform: [{ scale }],
                transformOrigin: 'top left',
              }}>
              <SharePoster ref={posterRef} issue={issue} poster={poster} onReady={() => setReady(true)} />
            </View>
          </View>
        </View>

        <Pressable
          onPress={share}
          disabled={busy || !ready}
          accessibilityRole="button"
          style={[styles.button, { backgroundColor: tone.ink, opacity: busy || !ready ? 0.5 : 1 }]}>
          {busy || !ready ? (
            <ActivityIndicator color={tone.bg} />
          ) : (
            <Text style={[t.display(16, '700'), { color: tone.bg }]}>Share</Text>
          )}
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1, paddingHorizontal: 24 },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 20,
    paddingBottom: 12,
  },
  stage: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  button: { height: 52, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
});
