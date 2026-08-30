import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import React, { useEffect } from 'react';
import { AppState, useColorScheme } from 'react-native';
import type { AppStateStatus } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ServicesProvider } from '../src/data/context';
import { useTone } from '../src/theme/tokens';

/** staleTime sits well inside the ten minutes a signed cover_url lasts, so a
 *  refetch always carries links that still resolve. */
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function RootLayout() {
  const scheme = useColorScheme();

  // React Query listens for window focus, which a native app never fires.
  // Without this, a feed left open past the signed-URL expiry comes back to
  // the foreground still holding dead image links.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state: AppStateStatus) => {
      focusManager.setFocused(state === 'active');
    });
    return () => subscription.remove();
  }, []);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={client}>
        <ServicesProvider>
          <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
          <Routes />
        </ServicesProvider>
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
      <Stack.Screen
        name="profile/edit"
        options={{ title: 'Your profile', presentation: 'modal' }}
      />
    </Stack>
  );
}
