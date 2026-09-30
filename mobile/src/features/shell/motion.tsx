import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, type ViewStyle } from 'react-native';

/** How far the incoming surface travels, in the direction of the switch. */
const SHIFT = 22;

/**
 * Honouring Reduce Motion is a system setting, not a preference we can guess,
 * so every animation here collapses to a jump when it is on.
 */
export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    let live = true;
    AccessibilityInfo.isReduceMotionEnabled().then((on) => {
      if (live) setReduced(on);
    });
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduced);
    return () => {
      live = false;
      sub.remove();
    };
  }, []);
  return reduced;
}

export function fadeTo(value: Animated.Value, toValue: number, still: boolean, duration = 180) {
  return Animated.timing(value, {
    toValue,
    duration: still ? 0 : duration,
    easing: Easing.out(Easing.quad),
    useNativeDriver: true,
  });
}

export function settleTo(value: Animated.Value, toValue: number, still: boolean) {
  if (still) return Animated.timing(value, { toValue, duration: 0, useNativeDriver: true });
  return Animated.spring(value, {
    toValue,
    stiffness: 220,
    damping: 24,
    mass: 1,
    useNativeDriver: true,
  });
}

/**
 * Fades the incoming screen up while it slides in from the side it came from,
 * so moving between sections reads as travel rather than a cut. `position` is
 * ordered, and its sign of change is the direction.
 */
export function SwitchView({
  position,
  style,
  children,
}: {
  position: number;
  style?: ViewStyle;
  children: React.ReactNode;
}) {
  const still = useReducedMotion();
  const shift = useRef(new Animated.Value(0)).current;
  const fade = useRef(new Animated.Value(1)).current;
  const previous = useRef(position);

  useLayoutEffect(() => {
    if (position === previous.current) return;
    const direction = position > previous.current ? 1 : -1;
    previous.current = position;
    if (still) {
      shift.setValue(0);
      fade.setValue(1);
      return;
    }

    shift.setValue(direction * SHIFT);
    fade.setValue(0);
    Animated.parallel([
      Animated.timing(shift, {
        toValue: 0,
        duration: 260,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(fade, {
        toValue: 1,
        duration: 200,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
    ]).start();
  }, [position, still, shift, fade]);

  return (
    <Animated.View style={[style, { opacity: fade, transform: [{ translateX: shift }] }]}>
      {children}
    </Animated.View>
  );
}
