import { useLocalSearchParams, useRouter } from 'expo-router';
import { Check, Eye, ImageIcon, MapPin, Plus, X } from 'lucide-react-native';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, Animated, Dimensions, Easing, Image, Keyboard, KeyboardAvoidingView,
  Modal, PanResponder, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput,
  useColorScheme, View,
} from 'react-native';
import MapView from 'react-native-maps';
import type { Region } from 'react-native-maps';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { useServices } from '../src/data/context';
import { capturedAt } from '../src/data/services';
import { CATEGORIES, MAX_PHOTOS, SEVERITIES, categoryLabel, severityLabel } from '../src/domain/issue';
import type { Category, Duplicate, GeoPoint, Severity } from '../src/domain/issue';
import { DuplicateSheet } from '../src/features/issues/DuplicateSheet';
import { metric, type as t, useTone } from '../src/theme/tokens';

const uuid = () =>
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });

/** The backend still wants a short title; one composer field feeds both, with
 *  the title clipped to the 140-char limit. */
const titleFrom = (caption: string) => {
  const text = caption.trim();
  if (text.length <= 140) return text;
  const cut = text.lastIndexOf(' ', 137);
  return `${text.slice(0, cut > 20 ? cut : 137).trimEnd()}…`;
};

/** The home screen takes the photos before opening this, and hands them over
 *  as a JSON array in the route params. */
const parseShots = (raw: string | undefined): string[] => {
  try {
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((u) => typeof u === 'string').slice(0, MAX_PHOTOS) : [];
  } catch {
    return [];
  }
};

const QUICK_CATEGORIES = CATEGORIES.slice(0, 3);
const PIN_DELTA = 0.004;

type Pin = { state: 'locating' } | { state: 'failed' } | { state: 'ready'; point: GeoPoint };

export default function Report() {
  const tone = useTone();
  const router = useRouter();
  const { auth, issues, location, photos } = useServices();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ photos?: string }>();
  const [caption, setCaption] = useState('');
  const [category, setCategory] = useState<Category>('pothole_road');
  const [severity, setSeverity] = useState<Severity>('medium');
  const [attached, setAttached] = useState<string[]>(() => parseShots(params.photos));
  /* Minted once per composer, not per tap. A failed publish is retried with
   * the same id, which is what lets the backend recognise the retry instead
   * of filing a second report. */
  const [reportId] = useState(uuid);
  const [busy, setBusy] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [pin, setPin] = useState<Pin>({ state: 'locating' });
  const [place, setPlace] = useState<string | null>(null);
  /* Held between the duplicate check and whatever the person chooses, so
   * neither branch has to ask the device for a fix a second time. */
  const [nearby, setNearby] = useState<{ point: GeoPoint; candidates: Duplicate[] } | null>(null);

  const locate = useCallback(() => {
    setPin({ state: 'locating' });
    location
      .current()
      .then((point) => setPin({ state: 'ready', point }))
      .catch(() => setPin({ state: 'failed' }));
  }, [location]);

  useEffect(locate, [locate]);

  const point = pin.state === 'ready' ? pin.point : null;
  useEffect(() => {
    if (!point) return;
    let live = true;
    setPlace(null);
    location.describe(point).then((line) => live && setPlace(line));
    return () => {
      live = false;
    };
  }, [point, location]);

  const full = attached.length >= MAX_PHOTOS;

  const addPhoto = async () => {
    if (full) return;
    try {
      Keyboard.dismiss();
      const shot = await photos.capture();
      if (shot) setAttached((prev) => [...prev, shot].slice(0, MAX_PHOTOS));
    } catch (e) {
      Alert.alert('Could not add photo', (e as Error).message);
    }
  };

  const publish = async () => {
    if (!auth.currentUserId()) return router.push('/auth');
    Keyboard.dismiss();
    setBusy(true);
    try {
      const at = point ?? (await location.current());
      const candidates = await issues.duplicates(at, category);
      if (candidates.length) {
        // Nothing is filed yet. The sheet decides where these photos go.
        setNearby({ point: at, candidates });
        return;
      }
      await file(at);
    } catch (e) {
      Alert.alert('Could not publish', (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const file = async (at: GeoPoint) => {
    const created = await issues.create({
      client_report_id: reportId,
      title: titleFrom(caption),
      description: caption.trim(),
      category,
      severity,
      latitude: at.latitude,
      longitude: at.longitude,
      locality: await location.locality(at),
      photos: attached,
    });
    setNearby(null);
    router.replace(`/issues/${created.id}`);
  };

  const addToExisting = async (issueId: string) => {
    setBusy(true);
    try {
      // Joining someone's report makes these photos evidence for it, so they
      // carry where the phone is now and when they were taken.
      await issues.support(issueId, {
        body: caption.trim(),
        photos: attached,
        point: await location.current(),
        captured_at: capturedAt(attached),
      });
      setNearby(null);
      router.replace(`/issues/${issueId}`);
    } catch (e) {
      Alert.alert('Could not add to that report', (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const postAnyway = async () => {
    if (!nearby) return;
    setBusy(true);
    try {
      await file(nearby.point);
    } catch (e) {
      Alert.alert('Could not publish', (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // A report is a photo plus a sentence, so the button says so by staying grey
  // rather than accepting the tap and refusing afterwards.
  // No pin, no post: a report is its place.
  const ready = attached.length > 0 && caption.trim().length >= 3 && !!point;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: tone.bg }}>
      <View style={[styles.bar, { borderBottomColor: tone.hairline }]}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={styles.barSide}>
          <X size={24} color={tone.ink} />
        </Pressable>
        <Text style={[t.display(18, '600'), { color: tone.ink }]}>New report</Text>
        <View style={[styles.barSide, { alignItems: 'flex-end' }]}>
          <Pressable
            disabled={busy || !ready}
            onPress={publish}
            style={[
              styles.publish,
              { backgroundColor: ready ? tone.accent : tone.surface, opacity: busy ? 0.5 : 1 },
            ]}>
            <Text style={[t.display(15, '600'), { color: ready ? '#000' : tone.chalk }]}>
              {busy ? 'Publishing' : 'Publish'}
            </Text>
          </Pressable>
        </View>
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={insets.top}>
        <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
          <PhotoRow
            photos={attached}
            onAdd={addPhoto}
            onOpen={setViewing}
            onDrop={(uri) => setAttached((prev) => prev.filter((u) => u !== uri))}
          />

          <View style={styles.section}>
            <Label text="What's wrong here?" />
            <TextInput
              autoFocus={attached.length > 0}
              style={[styles.caption, { color: tone.ink }]}
              value={caption}
              onChangeText={(text) => setCaption(text.replace(/\n/g, ' '))}
              multiline
              submitBehavior="blurAndSubmit"
              returnKeyType="done"
              maxLength={2000}
              placeholder="e.g. Deep pothole near the bus stop, bikes are swerving around it"
              placeholderTextColor={tone.chalk}
            />
          </View>

          <Divider />
          <View style={styles.section}>
            <Label text="Category" />
            <View style={styles.chips}>
              {[...QUICK_CATEGORIES, ...(QUICK_CATEGORIES.includes(category) ? [] : [category])].map(
                (value) => (
                  <Chip
                    key={value}
                    label={categoryLabel[value]}
                    on={value === category}
                    onPress={() => setCategory(value)}
                  />
                ),
              )}
              <Chip
                label="More"
                on={false}
                onPress={() => {
                  Keyboard.dismiss();
                  setMoreOpen(true);
                }}
              />
            </View>
          </View>

          <Divider />
          <View style={styles.section}>
            <Label text="Severity" />
            <SeveritySlider value={severity} onChange={setSeverity} />
          </View>

          <Divider />
          <View style={styles.section}>
            <View style={styles.labelRow}>
              <Label text="Location" />
              <Pressable
                disabled={!point}
                onPress={() => {
                  Keyboard.dismiss();
                  setAdjusting(true);
                }}
                hitSlop={10}>
                <Text style={[t.display(15, '500'), { color: point ? tone.accentDeep : tone.chalk }]}>
                  Adjust pin
                </Text>
              </Pressable>
            </View>
            <LocationRow pin={pin} place={place} onRetry={locate} />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      <DuplicateSheet
        visible={nearby !== null}
        candidates={nearby?.candidates ?? []}
        busy={busy}
        onAddTo={addToExisting}
        onPostNew={postAnyway}
        onDiscard={() => {
          setNearby(null);
          router.back();
        }}
      />

      <Sheet
        visible={moreOpen}
        onClose={() => setMoreOpen(false)}
        title="Category"
        options={CATEGORIES.map((v) => ({ value: v, label: categoryLabel[v], selected: v === category }))}
        onPick={(value) => {
          setCategory(value as Category);
          setMoreOpen(false);
        }}
      />

      {point && (
        <PinPicker
          visible={adjusting}
          start={point}
          onClose={() => setAdjusting(false)}
          onPick={(next) => {
            setPin({ state: 'ready', point: next });
            setAdjusting(false);
          }}
        />
      )}

      <Modal visible={viewing !== null} transparent animationType="fade" onRequestClose={() => setViewing(null)}>
        <Pressable style={styles.viewer} onPress={() => setViewing(null)}>
          {viewing && !viewing.startsWith('demo://') && (
            <Image source={{ uri: viewing }} style={styles.viewerImage} resizeMode="contain" />
          )}
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

function Label({ text }: { text: string }) {
  const tone = useTone();
  return <Text style={[t.body(15), { color: tone.chalk }]}>{text}</Text>;
}

function Divider() {
  const tone = useTone();
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: tone.hairline }} />;
}

const TILE_GAP = 10;

/** Every slot the report can hold, so how many more fit is visible at a glance. */
function PhotoRow({
  photos, onAdd, onOpen, onDrop,
}: {
  photos: string[];
  onAdd: () => void;
  onOpen: (uri: string) => void;
  onDrop: (uri: string) => void;
}) {
  const tone = useTone();
  const size = (Dimensions.get('window').width - metric.gutter * 2 - TILE_GAP * (MAX_PHOTOS - 1)) / MAX_PHOTOS;
  const open = MAX_PHOTOS - photos.length;

  return (
    <View style={styles.photos}>
      {photos.map((uri) => (
        <View key={uri} style={{ width: size, height: size }}>
          <Pressable onPress={() => onOpen(uri)} style={[styles.tile, { backgroundColor: tone.surface }]}>
            {uri.startsWith('demo://') ? (
              <ImageIcon size={26} color={tone.chalk} />
            ) : (
              <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
            )}
          </Pressable>
          <Pressable
            onPress={() => onDrop(uri)}
            hitSlop={8}
            accessibilityLabel="Remove photo"
            style={[styles.drop, { backgroundColor: tone.ink }]}>
            <X size={13} color={tone.bg} strokeWidth={3} />
          </Pressable>
        </View>
      ))}
      {Array.from({ length: open }, (_, i) => (
        <Pressable
          key={`slot-${i}`}
          onPress={onAdd}
          style={[
            styles.tile,
            { width: size, height: size, backgroundColor: tone.surface, opacity: i === 0 ? 1 : 0.5 },
          ]}>
          <Plus size={22} color={i === 0 ? tone.ink : tone.chalk} />
          <Text style={[t.body(13), { color: i === 0 ? tone.ink : tone.chalk, marginTop: 6 }]}>
            {i === 0 ? 'Add photo' : `${open - 1} more`}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

function Chip({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  const tone = useTone();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: on }}
      style={({ pressed }) => [
        styles.chip,
        { backgroundColor: on ? tone.ink : tone.surface, opacity: pressed ? 0.75 : 1 },
      ]}>
      <Text style={[t.display(15, on ? '600' : '400'), { color: on ? tone.bg : tone.ink }]}>{label}</Text>
    </Pressable>
  );
}

const THUMB = 26;

/**
 * Three stops on a rail. The thumb follows a drag freely and snaps to the
 * nearest stop on release; the colour shifts as soon as the nearest stop does,
 * so the choice is legible before the finger lifts.
 */
function SeveritySlider({ value, onChange }: { value: Severity; onChange: (next: Severity) => void }) {
  const tone = useTone();
  const colours = [tone.accent, tone.pending, tone.hazard];
  const [width, setWidth] = useState(0);
  const [live, setLive] = useState(SEVERITIES.indexOf(value));
  const x = useRef(new Animated.Value(0)).current;
  const span = Math.max(width - THUMB, 1);
  const geometry = useRef({ span, start: 0, live });
  geometry.current.span = span;

  const stopAt = (i: number) => (i * span) / (SEVERITIES.length - 1);

  const settle = useCallback(
    (i: number) => {
      Animated.spring(x, {
        toValue: (i * geometry.current.span) / (SEVERITIES.length - 1),
        stiffness: 320, damping: 26, mass: 0.8, useNativeDriver: false,
      }).start();
    },
    [x],
  );

  useEffect(() => {
    const i = SEVERITIES.indexOf(value);
    setLive(i);
    geometry.current.live = i;
    if (width) settle(i);
  }, [value, width, settle]);

  const responder = useMemo(() => {
    const clamp = (pos: number) => Math.min(Math.max(pos, 0), geometry.current.span);
    const track = (pos: number) => {
      const next = clamp(pos);
      x.setValue(next);
      const i = Math.round((next / geometry.current.span) * (SEVERITIES.length - 1));
      if (i !== geometry.current.live) {
        geometry.current.live = i;
        setLive(i);
      }
    };
    const release = () => {
      const i = geometry.current.live;
      settle(i);
      onChange(SEVERITIES[i]);
    };
    return PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: (e) => {
        Keyboard.dismiss();
        geometry.current.start = clamp(e.nativeEvent.locationX - THUMB / 2);
        track(geometry.current.start);
      },
      onPanResponderMove: (_, gesture) => track(geometry.current.start + gesture.dx),
      onPanResponderRelease: release,
      onPanResponderTerminate: release,
    });
  }, [x, settle, onChange]);

  const colour = colours[live];

  return (
    <View style={{ marginTop: 16 }}>
      <View
        {...responder.panHandlers}
        onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
        style={styles.rail}>
        <View pointerEvents="none" style={[styles.line, { backgroundColor: tone.hairline }]} />
        <Animated.View
          pointerEvents="none"
          style={[styles.line, { backgroundColor: colour, right: undefined, width: Animated.add(x, 1) }]}
        />
        {width > 0 &&
          SEVERITIES.map((s, i) => (
            <View
              key={s}
              pointerEvents="none"
              style={[
                styles.stop,
                { left: stopAt(i) + THUMB / 2 - 4, backgroundColor: i <= live ? colour : tone.chalk },
              ]}
            />
          ))}
        <Animated.View
          pointerEvents="none"
          style={[styles.thumb, { backgroundColor: `${colour}55`, transform: [{ translateX: x }] }]}>
          <View style={[styles.thumbCore, { backgroundColor: colour }]} />
        </Animated.View>
      </View>
      <View style={styles.severityLabels}>
        {SEVERITIES.map((s, i) => (
          <Pressable
            key={s}
            hitSlop={8}
            onPress={() => {
              Keyboard.dismiss();
              onChange(s);
            }}
            style={{ flex: 1, alignItems: i === 0 ? 'flex-start' : i === 2 ? 'flex-end' : 'center' }}>
            <Text
              style={[
                t.display(15, i === live ? '600' : '400'),
                { color: i === live ? colour : tone.chalk },
              ]}>
              {severityLabel[s]}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function MiniMap({ point }: { point: GeoPoint }) {
  const tone = useTone();
  const dark = useColorScheme() === 'dark';
  return (
    <View style={[styles.mini, { backgroundColor: tone.surface }]} pointerEvents="none">
      <MapView
        style={StyleSheet.absoluteFill}
        region={{ ...point, latitudeDelta: PIN_DELTA, longitudeDelta: PIN_DELTA }}
        liteMode
        userInterfaceStyle={dark ? 'dark' : 'light'}
        scrollEnabled={false}
        zoomEnabled={false}
        rotateEnabled={false}
        pitchEnabled={false}
        toolbarEnabled={false}
      />
      <View style={[styles.miniDot, { backgroundColor: tone.accent, borderColor: tone.bg }]} />
    </View>
  );
}

function LocationRow({ pin, place, onRetry }: { pin: Pin; place: string | null; onRetry: () => void }) {
  const tone = useTone();
  return (
    <View style={styles.locationRow}>
      {pin.state === 'ready' ? (
        <MiniMap point={pin.point} />
      ) : (
        <View style={[styles.mini, { backgroundColor: tone.surface }]}>
          {pin.state === 'locating' ? (
            <ActivityIndicator color={tone.accentDeep} />
          ) : (
            <MapPin size={22} color={tone.chalk} />
          )}
        </View>
      )}
      <View style={{ flex: 1, marginLeft: 16 }}>
        {pin.state === 'failed' ? (
          <Pressable onPress={onRetry} hitSlop={6}>
            <Text style={[t.display(16, '600'), { color: tone.ink }]}>Could not find you</Text>
            <Text style={[t.body(14), { color: tone.accentDeep, marginTop: 3 }]}>Try again</Text>
          </Pressable>
        ) : (
          <>
            <Text numberOfLines={2} style={[t.display(16, '600'), { color: tone.ink }]}>
              {pin.state === 'locating' ? 'Finding you…' : place ?? 'Pinned on the map'}
            </Text>
            <View style={styles.publicRow}>
              <Eye size={15} color={tone.chalk} />
              <Text style={[t.body(14), { color: tone.chalk, marginLeft: 6 }]}>Public on the map</Text>
            </View>
          </>
        )}
      </View>
    </View>
  );
}

/** The map moves under a fixed pin, which is easier to aim than dragging a marker. */
function PinPicker({
  visible, start, onClose, onPick,
}: {
  visible: boolean;
  start: GeoPoint;
  onClose: () => void;
  onPick: (point: GeoPoint) => void;
}) {
  const tone = useTone();
  const dark = useColorScheme() === 'dark';
  const { location } = useServices();
  const [centre, setCentre] = useState(start);
  const [line, setLine] = useState<string | null>(null);

  useEffect(() => {
    if (visible) setCentre(start);
  }, [visible, start]);

  useEffect(() => {
    if (!visible) return;
    let live = true;
    const timer = setTimeout(() => {
      location.describe(centre).then((next) => live && setLine(next));
    }, 350);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [centre, visible, location]);

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: tone.bg }}>
        <MapView
          style={StyleSheet.absoluteFill}
          initialRegion={{ ...start, latitudeDelta: PIN_DELTA, longitudeDelta: PIN_DELTA }}
          userInterfaceStyle={dark ? 'dark' : 'light'}
          showsUserLocation
          onRegionChangeComplete={(region: Region) =>
            setCentre({ latitude: region.latitude, longitude: region.longitude })
          }
        />
        <View pointerEvents="none" style={styles.centrePin}>
          <MapPin size={44} color="#000" fill={tone.accent} strokeWidth={1.5} />
        </View>

        <SafeAreaView edges={['top']} style={styles.pickerTop} pointerEvents="box-none">
          <Pressable onPress={onClose} hitSlop={10} style={[styles.round, { backgroundColor: tone.bg }]}>
            <X size={22} color={tone.ink} />
          </Pressable>
        </SafeAreaView>

        <SafeAreaView edges={['bottom']} style={[styles.pickerSheet, { backgroundColor: tone.bg }]}>
          <Text style={[t.body(14), { color: tone.chalk }]}>Move the map to place the pin</Text>
          <Text numberOfLines={2} style={[t.display(17, '600'), { color: tone.ink, marginTop: 4 }]}>
            {line ?? 'Pinned on the map'}
          </Text>
          <Pressable
            onPress={() => onPick(centre)}
            style={({ pressed }) => [styles.usePin, { backgroundColor: tone.accent, opacity: pressed ? 0.85 : 1 }]}>
            <Text style={[t.display(16, '600'), { color: '#000' }]}>Use this spot</Text>
          </Pressable>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

function Sheet({
  visible, onClose, title, options, onPick,
}: {
  visible: boolean;
  onClose: () => void;
  title: string;
  options: { value: string; label: string; selected: boolean }[];
  onPick: (value: string) => void;
}) {
  const tone = useTone();
  const insets = useSafeAreaInsets();
  const [mounted, setMounted] = useState(visible);
  const progress = useRef(new Animated.Value(0)).current;

  // The Modal's own slide moves the dimmed backdrop up with the sheet, so it
  // stays unanimated and the backdrop fades while only the sheet travels.
  useEffect(() => {
    if (visible) {
      setMounted(true);
      Animated.spring(progress, {
        toValue: 1, damping: 26, stiffness: 260, mass: 0.9, useNativeDriver: true,
      }).start();
    } else {
      Animated.timing(progress, {
        toValue: 0, duration: 180, easing: Easing.in(Easing.cubic), useNativeDriver: true,
      }).start(({ finished }) => finished && setMounted(false));
    }
  }, [visible, progress]);

  const travel = Dimensions.get('window').height * 0.6;
  return (
    <Modal visible={mounted} transparent animationType="none" statusBarTranslucent onRequestClose={onClose}>
      <Animated.View style={[StyleSheet.absoluteFill, styles.backdrop, { opacity: progress }]}>
        <Pressable style={{ flex: 1 }} onPress={onClose} />
      </Animated.View>
      <Animated.View
        style={[
          styles.sheet,
          {
            backgroundColor: tone.bg,
            paddingBottom: insets.bottom + 8,
            transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [travel, 0] }) }],
          },
        ]}>
        <View style={[styles.handle, { backgroundColor: tone.hairline }]} />
        <Text style={[t.display(16, '600'), { color: tone.ink, textAlign: 'center', marginBottom: 8 }]}>
          {title}
        </Text>
        <ScrollView bounces={false} style={{ flexShrink: 1 }} contentContainerStyle={{ paddingBottom: 4 }}>
          {options.map((option) => (
            <Pressable
              key={option.value}
              style={({ pressed }) => [styles.row, pressed && { backgroundColor: tone.surface }]}
              onPress={() => onPick(option.value)}>
              <Text style={[t.body(16), { color: tone.ink, flex: 1 }]}>{option.label}</Text>
              {option.selected && <Check size={18} color={tone.accentDeep} />}
            </Pressable>
          ))}
        </ScrollView>
      </Animated.View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: metric.gutter, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth,
  },
  barSide: { width: 96 },
  publish: { paddingHorizontal: 20, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  photos: {
    flexDirection: 'row', gap: TILE_GAP,
    paddingHorizontal: metric.gutter, paddingTop: 20, paddingBottom: 4,
  },
  tile: {
    flex: 1, borderRadius: 16, overflow: 'hidden',
    alignItems: 'center', justifyContent: 'center',
  },
  drop: {
    position: 'absolute', top: -7, right: -7, width: 26, height: 26, borderRadius: 13,
    alignItems: 'center', justifyContent: 'center',
  },
  section: { paddingHorizontal: metric.gutter, paddingVertical: 20 },
  labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  caption: {
    marginTop: 8, fontSize: 19, lineHeight: 26, minHeight: 56,
    textAlignVertical: 'top', padding: 0,
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 14 },
  chip: { paddingHorizontal: 18, paddingVertical: 11, borderRadius: 999 },
  rail: { height: THUMB + 12, justifyContent: 'center' },
  line: {
    position: 'absolute', left: THUMB / 2, right: THUMB / 2, height: 2, borderRadius: 1,
  },
  stop: { position: 'absolute', width: 8, height: 8, borderRadius: 4 },
  thumb: {
    position: 'absolute', left: 0, width: THUMB, height: THUMB, borderRadius: THUMB / 2,
    alignItems: 'center', justifyContent: 'center',
  },
  thumbCore: { width: 14, height: 14, borderRadius: 7 },
  severityLabels: { flexDirection: 'row', marginTop: 8 },
  locationRow: { flexDirection: 'row', alignItems: 'center', marginTop: 16 },
  mini: {
    width: 68, height: 68, borderRadius: 16, overflow: 'hidden',
    alignItems: 'center', justifyContent: 'center',
  },
  miniDot: { width: 16, height: 16, borderRadius: 8, borderWidth: 3 },
  publicRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4 },
  centrePin: {
    position: 'absolute', left: 0, right: 0, top: 0, bottom: 0,
    alignItems: 'center', justifyContent: 'center', paddingBottom: 44,
  },
  pickerTop: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: metric.gutter },
  round: {
    width: 42, height: 42, borderRadius: 21, marginTop: 8,
    alignItems: 'center', justifyContent: 'center',
  },
  pickerSheet: {
    position: 'absolute', left: 0, right: 0, bottom: 0,
    paddingHorizontal: metric.gutter, paddingTop: 18,
    borderTopLeftRadius: 22, borderTopRightRadius: 22,
  },
  usePin: {
    height: 52, borderRadius: 14, marginTop: 16, marginBottom: 8,
    alignItems: 'center', justifyContent: 'center',
  },
  viewer: { flex: 1, backgroundColor: 'rgba(0,0,0,0.94)', justifyContent: 'center' },
  viewerImage: { width: '100%', height: '75%' },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: metric.gutter, paddingVertical: 15 },
  backdrop: { backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: {
    position: 'absolute', left: 0, right: 0, bottom: 0, maxHeight: '60%',
    paddingTop: 8, borderTopLeftRadius: 18, borderTopRightRadius: 18,
  },
  handle: { alignSelf: 'center', width: 36, height: 5, borderRadius: 3, marginBottom: 10 },
});
