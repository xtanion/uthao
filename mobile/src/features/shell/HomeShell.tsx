import { useFocusEffect, useRouter } from 'expo-router';
import { Plus, User } from 'lucide-react-native';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Stop, Circle } from 'react-native-svg';
import { useServices } from '../../data/context';
import { useLocation, useProfile, useUnreadCount } from '../../data/queries';
import { Centered, LocationFailed, NearbyFeed } from '../issues/NearbyFeed';
import { MapScreen } from '../issues/MapScreen';
import { NotificationsScreen } from '../notifications/NotificationsScreen';
import { SearchScreen } from '../search/SearchScreen';
import { metric, type as t, useTone } from '../../theme/tokens';
import { Avatar } from '../profile/Avatar';
import { ChromeProvider, useBarOffset, useChrome } from './chrome';
import { NavIcon, type NavIconName } from './NavIcon';

const SECTIONS: NavIconName[] = ['house', 'search', 'bell'];

/** How far the FAB drops into the space the dock leaves behind. */
const DOCK_HEIGHT = 52;

export function HomeShell() {
  return (
    <ChromeProvider>
      <Shell />
    </ChromeProvider>
  );
}

function Shell() {
  const tone = useTone();
  const router = useRouter();
  const { auth } = useServices();
  const [tab, setTab] = useState(0);
  const [section, setSection] = useState(0);
  const { insets, measure, show } = useChrome();
  // Each bar clears its own height, so the shorter dock is gone while the
  // taller header is still on its way out — which is what X does.
  const headerOffset = useBarOffset(insets.top || 160);
  const dockOffset = useBarOffset(insets.bottom || DOCK_HEIGHT);
  const location = useLocation();

  // currentUserId is a plain read rather than state, so returning from the
  // sign-in route needs a nudge for the avatar and the activity gate to catch up.
  const [, setFocusTick] = useState(0);
  useFocusEffect(useCallback(() => setFocusTick((n) => n + 1), []));

  const signedIn = Boolean(auth.currentUserId());
  const unread = useUnreadCount(signedIn);
  const me = useProfile(signedIn ? auth.currentUserId() : null);

  const openSection = useCallback(
    (next: number) => {
      setSection(next);
      show();
    },
    [show],
  );


  return (
    <View style={{ flex: 1, backgroundColor: tone.bg }}>
      <View style={StyleSheet.absoluteFill}>
        {section === 2 ? (
          <NotificationsScreen />
        ) : (
          <>
            {location.isPending && <Centered><ActivityIndicator color={tone.accentDeep} /></Centered>}
            {location.isError && <LocationFailed error={location.error} onRetry={location.refetch} />}
            {location.data &&
              (section === 1 ? (
                <SearchScreen point={location.data} />
              ) : tab === 0 ? (
                <NearbyFeed point={location.data} />
              ) : (
                <MapScreen point={location.data} />
              ))}
          </>
        )}
      </View>

      <Animated.View
        onLayout={(e) => measure({ top: e.nativeEvent.layout.height })}
        style={[
          styles.topBar,
          {
            backgroundColor: tone.bg,
            transform: [{ translateY: Animated.multiply(headerOffset, -1) }],
          },
        ]}>
        <SafeAreaView edges={['top']}>
          <View style={styles.masthead}>
              <View style={{ width: 34 }} />
              <Mark />
              <Pressable
                onPress={() =>
                  router.push(signedIn ? `/users/${auth.currentUserId()}` : '/auth')
                }
                style={[
                  styles.avatar,
                  {
                    backgroundColor: tone.surface,
                    borderColor: signedIn ? tone.accent : tone.hairline,
                    borderWidth: signedIn ? 1.8 : 1,
                  },
                ]}>
                {me.data ? (
                  <Avatar
                    id={me.data.id}
                    name={me.data.display_name}
                    uri={me.data.avatar_url}
                    size={30}
                  />
                ) : (
                  <User size={19} color={tone.chalk} />
                )}
              </Pressable>
          </View>
          {section === 0 && (
            <View style={[styles.tabs, { borderBottomColor: tone.hairline }]}>
              {['Nearby', 'Map'].map((label, i) => (
                <Pressable key={label} style={styles.tab} onPress={() => setTab(i)}>
                  <Text style={[t.display(15, '700'), { color: i === tab ? tone.ink : tone.chalk }]}>
                    {label}
                  </Text>
                  <View
                    style={[
                      styles.indicator,
                      { backgroundColor: i === tab ? tone.accent : 'transparent' },
                    ]}
                  />
                </Pressable>
              ))}
            </View>
          )}
        </SafeAreaView>
      </Animated.View>

      <Animated.View
        style={[
          styles.fab,
          {
            transform: [{ translateY: dockOffset }],
          },
        ]}>
        <Pressable
          onPress={() => router.push('/report')}
          style={[styles.fabButton, { backgroundColor: tone.accent }]}>
          <Plus size={30} color="#000" />
        </Pressable>
      </Animated.View>

      <Animated.View
        onLayout={(e) => measure({ bottom: e.nativeEvent.layout.height })}
        style={[
          styles.dock,
          {
            backgroundColor: tone.bg,
            transform: [{ translateY: dockOffset }],
          },
        ]}>
        <SafeAreaView edges={['bottom']}>
          <View style={[styles.sectionBar, { borderTopColor: tone.hairline }]}>
            {SECTIONS.map((name, i) => (
              <Pressable key={name} style={styles.section} onPress={() => openSection(i)}>
                <NavIcon
                  name={name}
                  filled={i === section}
                  color={i === section ? tone.accentDeep : tone.chalk}
                />
                {name === 'bell' && unread > 0 && (
                  <View style={[styles.badge, { backgroundColor: tone.accent, borderColor: tone.bg }]}>
                    <Text style={[t.meta(10, '700', 0), { color: '#000' }]}>
                      {unread > 9 ? '9+' : unread}
                    </Text>
                  </View>
                )}
              </Pressable>
            ))}
          </View>
        </SafeAreaView>
      </Animated.View>
    </View>
  );
}

/** The app mark: a single gradient dot, no wordmark. */
function Mark() {
  const tone = useTone();
  return (
    <Svg width={26} height={26} viewBox="0 0 26 26">
      <Defs>
        <LinearGradient id="mark" x1="0" y1="0" x2="1" y2="1">
          <Stop offset="0" stopColor={tone.accentSoft} />
          <Stop offset="1" stopColor={tone.accentDeep} />
        </LinearGradient>
      </Defs>
      <Circle cx={13} cy={13} r={13} fill="url(#mark)" />
    </Svg>
  );
}

const styles = StyleSheet.create({
  masthead: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: metric.gutter, paddingTop: 10, paddingBottom: 24,
  },
  avatar: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  tabs: { flexDirection: 'row', borderBottomWidth: 1 },
  tab: { flex: 1, alignItems: 'center', paddingTop: 2 },
  indicator: { height: 3, width: 34, borderRadius: 2, marginTop: 8 },
  fab: { position: 'absolute', right: 20, bottom: 90, width: 58, height: 58 },
  fabButton: {
    width: 58, height: 58, borderRadius: 29,
    alignItems: 'center', justifyContent: 'center',
  },
  topBar: { position: 'absolute', top: 0, left: 0, right: 0, zIndex: 2 },
  dock: { position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 2 },
  sectionBar: { flexDirection: 'row', height: DOCK_HEIGHT, borderTopWidth: 1 },
  section: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  badge: {
    position: 'absolute', top: 8, left: '54%', minWidth: 17, height: 17,
    borderRadius: 9, borderWidth: 2, paddingHorizontal: 4,
    alignItems: 'center', justifyContent: 'center',
  },
});
