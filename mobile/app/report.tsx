import { useLocalSearchParams, useRouter } from 'expo-router';
import { Camera, Check, ChevronRight, MapPin, Plus, X } from 'lucide-react-native';
import React, { useEffect, useRef, useState } from 'react';
import {
  Alert, Animated, Dimensions, Easing, Image, InputAccessoryView, Keyboard, KeyboardAvoidingView,
  Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { useServices } from '../src/data/context';
import { CATEGORIES, MAX_PHOTOS, SEVERITIES, categoryLabel, severityLabel } from '../src/domain/issue';
import type { Category, Duplicate, GeoPoint, Severity } from '../src/domain/issue';
import { DuplicateSheet } from '../src/features/issues/DuplicateSheet';
import { CategoryGlyph } from '../src/features/issues/glyphs';
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
  /* Kept after the sheet closes so its contents do not swap to the other
   * list while it is still sliding away. */
  const [sheet, setSheet] = useState<'category' | 'severity'>('category');
  const [sheetOpen, setSheetOpen] = useState(false);
  /* Held between the duplicate check and whatever the person chooses, so
   * neither branch has to ask the device for a fix a second time. */
  const [nearby, setNearby] = useState<{ point: GeoPoint; candidates: Duplicate[] } | null>(null);

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
    setBusy(true);
    try {
      const point = await location.current();
      const candidates = await issues.duplicates(point, category);
      if (candidates.length) {
        // Nothing is filed yet. The sheet decides where these photos go.
        setNearby({ point, candidates });
        return;
      }
      await file(point);
    } catch (e) {
      Alert.alert('Could not publish', (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const file = async (point: GeoPoint) => {
    const created = await issues.create({
      client_report_id: reportId,
      title: titleFrom(caption),
      description: caption.trim(),
      category,
      severity,
      latitude: point.latitude,
      longitude: point.longitude,
      photos: attached,
    });
    setNearby(null);
    router.replace(`/issues/${created.id}`);
  };

  const addToExisting = async (issueId: string) => {
    setBusy(true);
    try {
      await issues.support(issueId, { body: caption.trim(), photos: attached });
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
  const ready = attached.length > 0 && caption.trim().length >= 3;
  const wellHeight = Dimensions.get('window').height * 0.44;
  const [typing, setTyping] = useState(false);

  const openSheet = (which: 'category' | 'severity') => {
    Keyboard.dismiss();
    setSheet(which);
    setSheetOpen(true);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: tone.bg }}>
      <View style={[styles.bar, { borderBottomColor: tone.hairline }]}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <X size={24} color={tone.ink} />
        </Pressable>
        <Text style={[t.display(18, '600'), { color: tone.ink }]}>New report</Text>
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

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={insets.top}>
        <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
          <PhotoWell
            photos={attached}
            height={wellHeight}
            full={full}
            onAdd={addPhoto}
            onDrop={(uri) => setAttached((prev) => prev.filter((u) => u !== uri))}
          />

          <TextInput
            autoFocus={attached.length > 0}
            style={[styles.caption, { color: tone.ink }]}
            value={caption}
            onChangeText={setCaption}
            multiline
            maxLength={2000}
            placeholder="What is wrong here?"
            placeholderTextColor={tone.chalk}
            inputAccessoryViewID={DONE_BAR}
            onFocus={() => setTyping(true)}
            onBlur={() => setTyping(false)}
          />
          {Platform.OS !== 'ios' && typing && (
            <Pressable onPress={Keyboard.dismiss} hitSlop={8} style={styles.doneInline}>
              <Text style={[t.display(15, '600'), { color: tone.accentDeep }]}>Done</Text>
            </Pressable>
          )}

          <Divider />
          <Row
            leading={<CategoryGlyph category={category} size={20} color={tone.ink} />}
            label="Category"
            value={categoryLabel[category]}
            onPress={() => openSheet('category')}
          />
          <Divider />
          <Row
            leading={
              <View
                style={[
                  styles.dot,
                  { backgroundColor: severity === 'high' ? tone.hazard : severity === 'medium' ? tone.ink : tone.chalk },
                ]}
              />
            }
            label="Severity"
            value={severityLabel[severity]}
            onPress={() => openSheet('severity')}
          />
          <Divider />
          <Row
            leading={<MapPin size={20} color={tone.chalk} />}
            label="Location"
            value="Added when you publish"
          />
          <Text style={[t.meta(11, '500', 0.6), { color: tone.chalk, padding: metric.gutter }]}>
            This location will be public.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>

      {Platform.OS === 'ios' && (
        <InputAccessoryView nativeID={DONE_BAR}>
          <View style={[styles.doneBar, { backgroundColor: tone.surface, borderTopColor: tone.hairline }]}>
            <Pressable onPress={Keyboard.dismiss} hitSlop={10}>
              <Text style={[t.display(15, '600'), { color: tone.accentDeep }]}>Done</Text>
            </Pressable>
          </View>
        </InputAccessoryView>
      )}

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
        visible={sheetOpen}
        onClose={() => setSheetOpen(false)}
        title={sheet === 'severity' ? 'Severity' : 'Category'}
        options={
          sheet === 'severity'
            ? SEVERITIES.map((v) => ({ value: v, label: severityLabel[v], selected: v === severity }))
            : CATEGORIES.map((v) => ({ value: v, label: categoryLabel[v], selected: v === category }))
        }
        onPick={(value) => {
          if (sheet === 'severity') setSeverity(value as Severity);
          else setCategory(value as Category);
          setSheetOpen(false);
        }}
      />
    </SafeAreaView>
  );
}

const DONE_BAR = 'report-caption-done';

/**
 * Every photo taken so far, one page each, with a strip underneath that says
 * how many are attached and where the next one goes. Coming back from the
 * camera lands on the newest page, so the shot visibly registered.
 */
function PhotoWell({
  photos, height, full, onAdd, onDrop,
}: {
  photos: string[];
  height: number;
  full: boolean;
  onAdd: () => void;
  onDrop: (uri: string) => void;
}) {
  const tone = useTone();
  const width = Dimensions.get('window').width;
  const pager = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);
  const seen = useRef(photos.length);

  useEffect(() => {
    if (photos.length > seen.current) {
      const last = photos.length - 1;
      requestAnimationFrame(() => pager.current?.scrollTo({ x: last * width, animated: true }));
      setPage(last);
    } else if (page > photos.length - 1) {
      setPage(Math.max(photos.length - 1, 0));
    }
    seen.current = photos.length;
  }, [photos.length, page, width]);

  if (!photos.length) {
    return (
      <Pressable onPress={onAdd} style={[styles.well, { height }]}>
        <View style={[styles.disc, { backgroundColor: tone.surface }]}>
          <Camera size={34} color={tone.ink} />
        </View>
        <Text style={[t.display(15, '500'), { color: tone.ink, marginTop: 16 }]}>
          Tap to take a photo
        </Text>
        <Text style={[t.meta(11, '500', 0.6), { color: tone.chalk, marginTop: 4 }]}>
          Take one here; you cannot choose from your library
        </Text>
      </Pressable>
    );
  }

  return (
    <View>
      <View style={{ height, backgroundColor: tone.surface }}>
        <ScrollView
          ref={pager}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          onMomentumScrollEnd={(e) => setPage(Math.round(e.nativeEvent.contentOffset.x / width))}>
          {photos.map((uri) => (
            <View key={uri} style={{ width, height }}>
              {uri.startsWith('demo://') ? (
                <View style={styles.well}>
                  <Camera size={34} color={tone.chalk} />
                </View>
              ) : (
                <Image source={{ uri }} style={{ flex: 1 }} resizeMode="cover" />
              )}
            </View>
          ))}
        </ScrollView>
        {photos.length > 1 && (
          <View style={styles.counter}>
            <Text style={[t.meta(12, '600', 0.2), { color: '#fff' }]}>
              {page + 1} / {photos.length}
            </Text>
          </View>
        )}
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.strip}>
        {photos.map((uri, i) => (
          <Pressable
            key={uri}
            onPress={() => {
              pager.current?.scrollTo({ x: i * width, animated: true });
              setPage(i);
            }}
            style={styles.thumbWrap}>
            {uri.startsWith('demo://') ? (
              <View
                style={[
                  styles.thumb, styles.well,
                  { backgroundColor: tone.surface, borderColor: i === page ? tone.accent : 'transparent' },
                ]}>
                <Camera size={16} color={tone.chalk} />
              </View>
            ) : (
              <Image
                source={{ uri }}
                style={[styles.thumb, { borderColor: i === page ? tone.accent : 'transparent' }]}
              />
            )}
            <Pressable
              onPress={() => onDrop(uri)}
              hitSlop={8}
              accessibilityLabel="Remove photo"
              style={[styles.drop, { backgroundColor: tone.ink }]}>
              <X size={11} color={tone.bg} strokeWidth={3} />
            </Pressable>
          </Pressable>
        ))}
        {!full && (
          <Pressable onPress={onAdd} style={[styles.thumb, styles.addTile, { borderColor: tone.hairline }]}>
            <Plus size={18} color={tone.ink} />
            <Text style={[t.meta(10, '500', 0), { color: tone.chalk, marginTop: 2 }]}>
              {MAX_PHOTOS - photos.length} left
            </Text>
          </Pressable>
        )}
        <View style={styles.tally}>
          <Text style={[t.meta(12, '600', 0), { color: tone.ink }]}>
            {photos.length} photo{photos.length === 1 ? '' : 's'} attached
          </Text>
          {full && (
            <Text style={[t.meta(11, '500', 0), { color: tone.chalk, marginTop: 2 }]}>
              {MAX_PHOTOS} is the most
            </Text>
          )}
        </View>
      </ScrollView>
    </View>
  );
}

function Divider() {
  const tone = useTone();
  return <View style={{ height: 1, backgroundColor: tone.hairline }} />;
}

function Row({
  leading, label, value, onPress,
}: { leading: React.ReactNode; label: string; value: string; onPress?: () => void }) {
  const tone = useTone();
  return (
    <Pressable onPress={onPress} style={styles.row}>
      <View style={{ width: 22, alignItems: 'center' }}>{leading}</View>
      <Text style={[t.display(15, '500'), { color: tone.ink, marginLeft: 12 }]}>{label}</Text>
      <View style={{ flex: 1 }} />
      <Text style={[t.body(15), { color: tone.chalk }]}>{value}</Text>
      {onPress && <ChevronRight size={17} color={tone.chalk} style={{ marginLeft: 6 }} />}
    </Pressable>
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
    paddingHorizontal: metric.gutter, paddingVertical: 10, borderBottomWidth: 1,
  },
  publish: { paddingHorizontal: 20, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  well: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  disc: {
    width: 84, height: 84, borderRadius: 42,
    alignItems: 'center', justifyContent: 'center',
  },
  caption: {
    paddingHorizontal: metric.gutter, paddingTop: 16, paddingBottom: 8,
    fontSize: 17, minHeight: 72, textAlignVertical: 'top',
  },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: metric.gutter, paddingVertical: 15 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  counter: {
    position: 'absolute', top: 12, right: 12, paddingHorizontal: 9, paddingVertical: 4,
    borderRadius: 999, backgroundColor: 'rgba(0,0,0,0.55)',
  },
  strip: { paddingHorizontal: metric.gutter, paddingTop: 12, alignItems: 'center' },
  thumbWrap: { marginRight: 10 },
  thumb: { width: 56, height: 56, borderRadius: 9, borderWidth: 2 },
  drop: {
    position: 'absolute', top: -5, right: -5, width: 18, height: 18, borderRadius: 9,
    alignItems: 'center', justifyContent: 'center',
  },
  addTile: { borderStyle: 'dashed', borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  tally: { marginLeft: 14 },
  doneInline: { alignSelf: 'flex-end', paddingHorizontal: metric.gutter, paddingBottom: 10 },
  doneBar: {
    flexDirection: 'row', justifyContent: 'flex-end', paddingHorizontal: metric.gutter,
    paddingVertical: 10, borderTopWidth: StyleSheet.hairlineWidth,
  },
  backdrop: { backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: {
    position: 'absolute', left: 0, right: 0, bottom: 0, maxHeight: '60%',
    paddingTop: 8, borderTopLeftRadius: 18, borderTopRightRadius: 18,
  },
  handle: { alignSelf: 'center', width: 36, height: 5, borderRadius: 3, marginBottom: 10 },
});
