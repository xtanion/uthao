import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Animated, Easing } from 'react-native';

export type ChromeInsets = { top: number; bottom: number };

type Chrome = {
  /** Scroll position of whatever list is on screen. Everything derives from it. */
  scrollY: Animated.Value;
  /** How much room the bars cover, so content can clear them. */
  insets: ChromeInsets;
  measure: (next: Partial<ChromeInsets>) => void;
  /** For surfaces that do not scroll: the map hides on pan, returns on tap. */
  show: () => void;
  hide: () => void;
};

const ChromeContext = createContext<Chrome | null>(null);

/** Far enough that both bars are fully clear when driven by hand. */
const AWAY = 220;

/**
 * The bars are tied to the scroll position rather than toggled.
 *
 * A timed animation cannot match a finger: it starts after a threshold is
 * crossed and then runs at its own speed, which is what made this feel like it
 * was catching up rather than moving with the content. Reading the offset and
 * clamping the delta means the bars travel exactly as far as the scroll does,
 * reverse the instant the direction does, and never animate on a clock at all.
 */
export function ChromeProvider({ children }: { children: React.ReactNode }) {
  const [insets, setInsets] = useState<ChromeInsets>({ top: 0, bottom: 0 });
  const scrollY = useRef(new Animated.Value(0)).current;

  const measure = useCallback((next: Partial<ChromeInsets>) => {
    setInsets((current) => {
      const merged = { ...current, ...next };
      return merged.top === current.top && merged.bottom === current.bottom
        ? current
        : merged;
    });
  }, []);

  // A non-scrolling surface has no offset to read, so it drives the same value
  // by hand and the bars behave identically either way.
  const drive = useCallback(
    (to: number) => {
      Animated.timing(scrollY, {
        toValue: to,
        duration: 220,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }).start();
    },
    [scrollY],
  );

  const value = useMemo(
    () => ({
      scrollY,
      insets,
      measure,
      show: () => drive(0),
      hide: () => drive(AWAY),
    }),
    [scrollY, insets, measure, drive],
  );
  return <ChromeContext.Provider value={value}>{children}</ChromeContext.Provider>;
}

export function useChrome(): Chrome {
  const chrome = useContext(ChromeContext);
  if (!chrome) throw new Error('useChrome must be used inside ChromeProvider');
  return chrome;
}

/**
 * Spread onto an Animated.FlatList or Animated.ScrollView. Native-driven, so
 * the bars move on the UI thread and a slow render cannot stutter them.
 */
export function useChromeOnScroll() {
  const { scrollY } = useChrome();
  return useMemo(
    () => ({
      onScroll: Animated.event(
        [{ nativeEvent: { contentOffset: { y: scrollY } } }],
        { useNativeDriver: true },
      ),
      scrollEventThrottle: 16,
    }),
    [scrollY],
  );
}

/**
 * How far a bar of this height should be pushed away, given where the list is.
 *
 * diffClamp accumulates the *change* in offset rather than the offset itself,
 * so reversing by ten points brings the bar back ten points — the behaviour
 * that makes it feel attached to the content instead of triggered by it.
 */
export function useBarOffset(height: number) {
  const { scrollY } = useChrome();
  return useMemo(() => {
    // Overscroll at the top drives contentOffset negative, and the rebound
    // back to zero is a positive delta — which diffClamp would read as a
    // downward scroll and use to push the bars away. Pulling to refresh would
    // therefore hide the chrome on release. Flattening everything above the
    // top to zero means the bounce is never seen as scrolling at all.
    const downward = scrollY.interpolate({
      inputRange: [0, 1],
      outputRange: [0, 1],
      extrapolateLeft: 'clamp',
    });
    return Animated.diffClamp(downward, 0, Math.max(height, 1));
  }, [scrollY, height]);
}

/** Padding that keeps list content clear of the overlaid bars. */
export function useChromeSpacing(extraBottom = 0) {
  const { insets } = useChrome();
  return {
    paddingTop: insets.top,
    paddingBottom: insets.bottom + extraBottom,
  };
}
