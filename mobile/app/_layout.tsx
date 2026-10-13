import {
  QueryClient,
  QueryClientProvider,
  focusManager,
  onlineManager,
} from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import type { Theme } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SystemUI from 'expo-system-ui';
import React, { useEffect } from 'react';
import * as Network from 'expo-network';
import { AppState, useColorScheme } from 'react-native';
import type { AppStateStatus } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ServicesProvider } from '../src/data/context';
import { dark, light, useTone } from '../src/theme/tokens';
import type { Tones } from '../src/theme/tokens';

/** staleTime sits well inside the ten minutes a signed cover_url lasts, so a
 *  refetch always carries links that still resolve. */
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

const themeFor = (base: Theme, tone: Tones): Theme => ({
  ...base,
  colors: {
    ...base.colors,
    primary: tone.accentDeep,
    background: tone.bg,
    card: tone.bg,
    text: tone.ink,
    border: tone.hairline,
  },
});

const darkTheme = themeFor(DarkTheme, dark);
const lightTheme = themeFor(DefaultTheme, light);

export default function RootLayout() {
  const scheme = useColorScheme();
  const [fontsLoaded, fontError] = useFonts({
    'GeistPixel-Square': require('../assets/fonts/GeistPixel-Square.ttf'),
  });

  // React Query listens for window focus, which a native app never fires.
  // Without this, a feed left open past the signed-URL expiry comes back to
  // the foreground still holding dead image links.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state: AppStateStatus) => {
      focusManager.setFocused(state === 'active');
    });
    return () => subscription.remove();
  }, []);

  // And it assumes it is online unless told otherwise, which on a phone means
  // refetchOnReconnect never fires. Reporting happens outdoors on patchy
  // mobile data, so coming back into signal is the moment a stale feed most
  // needs to catch up.
  useEffect(() => {
    const subscription = Network.addNetworkStateListener((state) => {
      onlineManager.setOnline(Boolean(state.isInternetReachable ?? state.isConnected));
    });
    Network.getNetworkStateAsync()
      .then((state) =>
        onlineManager.setOnline(Boolean(state.isInternetReachable ?? state.isConnected)),
      )
      .catch(() => onlineManager.setOnline(true));
    return () => subscription.remove();
  }, []);

  // The navigation theme decides the native header's interface style, so
  // without it the iOS glass bar buttons render light in dark mode. The root
  // view colour is what shows at the corners while a screen slides in.
  useEffect(() => {
    void SystemUI.setBackgroundColorAsync(scheme === 'dark' ? dark.bg : light.bg);
  }, [scheme]);

  if (!fontsLoaded && !fontError) return null;

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={client}>
        <ThemeProvider value={scheme === 'dark' ? darkTheme : lightTheme}>
          <ServicesProvider>
            <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
            <Routes />
          </ServicesProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}

function Routes() {
  const tone = useTone();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: tone.bg },
        headerTintColor: tone.ink,
        headerShadowVisible: false,
        // Otherwise iOS labels the back button with the previous route's
        // title, which for the shell is literally "index".
        headerBackButtonDisplayMode: 'minimal',
        contentStyle: { backgroundColor: tone.bg },
      }}>
      <Stack.Screen name="index" options={{ headerShown: false }} />
      <Stack.Screen name="onboarding" options={{ headerShown: false }} />
      <Stack.Screen name="auth" options={{ title: 'Sign in' }} />
      <Stack.Screen name="report" options={{ headerShown: false, presentation: 'modal' }} />
      <Stack.Screen name="issues/[id]" options={{ title: '' }} />
      <Stack.Screen name="users/[id]" options={{ title: '' }} />
      <Stack.Screen name="profile/edit" options={{ title: 'Your profile' }} />
    </Stack>
  );
}
