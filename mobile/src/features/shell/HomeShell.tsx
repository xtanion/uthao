import { useFocusEffect, useRouter } from 'expo-router';
import { Camera, User } from 'lucide-react-native';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Stop, Circle } from 'react-native-svg';
import { useServices } from '../../data/context';
import { useLocation, useProfile, useUnreadCount } from '../../data/queries';
import { Centered, LocationFailed, NearbyFeed } from '../issues/NearbyFeed';
import { MapScreen } from '../issues/MapScreen';
import { NotificationsScreen } from '../notifications/NotificationsScreen';
import { usePushNotifications } from '../notifications/usePushNotifications';
import { SearchScreen } from '../search/SearchScreen';
import { StatsScreen } from '../stats/StatsScreen';
import { metric, type as t, useTone } from '../../theme/tokens';
import { Avatar } from '../profile/Avatar';
import { ChromeProvider, useBarOffset, useChrome } from './chrome';
import { NavIcon, type NavIconName } from './NavIcon';
import { fadeTo, settleTo, SwitchView, useReducedMotion } from './motion';

const SECTIONS: NavIconName[] = ['house', 'search', 'chart', 'bell'];

/** How far the FAB drops into the space the dock leaves behind. */
const DOCK_HEIGHT = 52;

const ICON = 25;
const FAB_MARGIN = 20;
const INDICATOR = 34;

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
  const { auth, photos } = useServices();
  const [tab, setTab] = useState(0);
  const [section, setSection] = useState(0);
  const [tabWidth, setTabWidth] = useState(0);
  const still = useReducedMotion();
  const tabSlide = useRef(new Animated.Value(0)).current;
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
  usePushNotifications(signedIn, unread);

  // The camera opens before the composer, so backing out of it leaves the
  // person on the feed rather than in an empty report they have to dismiss.
  const capturing = useRef(false);
  const startReport = useCallback(async () => {
    if (capturing.current) return;
    capturing.current = true;
    try {
      const shot = await photos.capture();
      if (shot) {
        router.push({ pathname: '/report', params: { photos: JSON.stringify([shot]) } });
      }
    } catch (e) {
      Alert.alert('Could not open the camera', (e as Error).message);
    } finally {
      capturing.current = false;
    }
  }, [photos, router]);

  const openSection = useCallback(
    (next: number) => {
      setSection(next);
      show();
    },
    [show],
  );

  const openMap = useCallback(() => {
    setTab(1);
    openSection(0);
  }, [openSection]);

  useEffect(() => {
    settleTo(tabSlide, tab, still).start();
  }, [tab, still, tabSlide]);

  return (
    <View style={{ flex: 1, backgroundColor: tone.bg }}>
      <SwitchView position={section * 10 + tab} style={StyleSheet.absoluteFill}>
        {section === 3 ? (
          <NotificationsScreen />
        ) : section === 2 ? (
          <StatsScreen onOpenMap={openMap} />
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
      </SwitchView>

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
            <View
              style={[styles.tabs, { borderBottomColor: tone.hairline }]}
              onLayout={(e) => setTabWidth(e.nativeEvent.layout.width / 2)}>
              {['Nearby', 'Map'].map((label, i) => (
                <Pressable key={label} style={styles.tab} onPress={() => setTab(i)}>
                  <Animated.Text
                    style={[
                      t.display(15, '700'),
                      {
                        color: tone.ink,
                        opacity: tabSlide.interpolate({
                          inputRange: [0, 1],
                          outputRange: i === 0 ? [1, 0.45] : [0.45, 1],
                          extrapolate: 'clamp',
                        }),
                      },
                    ]}>
                    {label}
                  </Animated.Text>
                </Pressable>
              ))}
              {tabWidth > 0 && (
                <Animated.View
                  style={[
                    styles.indicator,
                    {
                      backgroundColor: tone.accent,
                      transform: [
                        {
                          translateX: tabSlide.interpolate({
                            inputRange: [0, 1],
                            outputRange: [
                              (tabWidth - INDICATOR) / 2,
                              tabWidth + (tabWidth - INDICATOR) / 2,
                            ],
                          }),
                        },
                      ],
                    },
                  ]}
                />
              )}
            </View>
          )}
        </SafeAreaView>
      </Animated.View>

      <Animated.View
        style={[
          styles.fab,
          {
            bottom: (insets.bottom || DOCK_HEIGHT) + FAB_MARGIN,
            transform: [{ translateY: dockOffset }],
          },
        ]}>
        <Pressable
          onPress={startReport}
          accessibilityLabel="Report a problem"
          style={({ pressed }) => [
            styles.fabButton,
            { backgroundColor: tone.accent, transform: [{ scale: pressed ? 0.94 : 1 }] },
          ]}>
          <Camera size={26} color="#000" strokeWidth={2.2} />
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
              <SectionButton
                key={name}
                name={name}
                active={i === section}
                still={still}
                onPress={() => openSection(i)}>
                {name === 'bell' && unread > 0 && (
                  <View style={[styles.badge, { backgroundColor: tone.accent, borderColor: tone.bg }]}>
                    <Text style={[t.meta(10, '700', 0), { color: '#000' }]}>
                      {unread > 9 ? '9+' : unread}
                    </Text>
                  </View>
                )}
              </SectionButton>
            ))}
          </View>
        </SafeAreaView>
      </Animated.View>
    </View>
  );
}

/**
 * The two weights of the glyph are stacked and cross-faded, so selecting a
 * section shifts its colour and fill together instead of snapping.
 */
function SectionButton({
  name,
  active,
  still,
  onPress,
  children,
}: {
  name: NavIconName;
  active: boolean;
  still: boolean;
  onPress: () => void;
  children?: React.ReactNode;
}) {
  const tone = useTone();
  const lit = useRef(new Animated.Value(active ? 1 : 0)).current;
  const scale = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    fadeTo(lit, active ? 1 : 0, still).start();
  }, [active, still, lit]);

  const press = () => {
    if (!still) {
      Animated.sequence([
        Animated.timing(scale, { toValue: 0.86, duration: 90, useNativeDriver: true }),
        Animated.spring(scale, {
          toValue: 1,
          stiffness: 400,
          damping: 12,
          mass: 0.6,
          useNativeDriver: true,
        }),
      ]).start();
    }
    onPress();
  };

  return (
    <Pressable style={styles.section} onPress={press}>
      <Animated.View style={{ width: ICON, height: ICON, transform: [{ scale }] }}>
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: Animated.subtract(1, lit) }]}>
          <NavIcon name={name} filled={false} color={tone.chalk} size={ICON} />
        </Animated.View>
        <Animated.View style={[StyleSheet.absoluteFill, { opacity: lit }]}>
          <NavIcon name={name} filled color={tone.accentDeep} size={ICON} />
        </Animated.View>
      </Animated.View>
      {children}
    </Pressable>
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
  tabs: { flexDirection: 'row', borderBottomWidth: 1, paddingBottom: 11 },
  tab: { flex: 1, alignItems: 'center', paddingTop: 2 },
  indicator: {
    position: 'absolute', left: 0, bottom: 0,
    height: 3, width: INDICATOR, borderRadius: 2,
  },
  fab: { position: 'absolute', right: FAB_MARGIN, width: 58, height: 58 },
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
