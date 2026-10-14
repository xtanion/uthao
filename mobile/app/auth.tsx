import { useNavigation, useRouter } from 'expo-router';
import type { NativeStackNavigationProp } from 'expo-router/native-stack';
import React, { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useServices } from '../src/data/context';
import { metric, type as t, useTone } from '../src/theme/tokens';

const COUNTRY_CODE = '+91';
const DIGITS = 10;

// maxLength is enforced here rather than on the input: it would truncate a
// pasted "+91 98765 43210" before it could be cleaned.
const nationalNumber = (text: string) => {
  let digits = text.replace(/\D/g, '');
  if (digits.length > DIGITS && digits.startsWith('91')) digits = digits.slice(2);
  if (digits.startsWith('0')) digits = digits.slice(1);
  return digits.slice(0, DIGITS);
};

export default function Auth() {
  const tone = useTone();
  const router = useRouter();
  const { auth } = useServices();
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigation = useNavigation<NativeStackNavigationProp<Record<string, undefined>>>();
  const phoneField = useRef<TextInput>(null);

  // autoFocus raised the keyboard while the screen was still sliding in, and
  // the two animations fighting is what made the push stutter.
  useEffect(
    () =>
      navigation.addListener('transitionEnd', (e) => {
        if (!e.data.closing) phoneField.current?.focus();
      }),
    [navigation],
  );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (sent) {
        await auth.verifyOtp(`${COUNTRY_CODE}${phone}`, code.trim());
        router.back();
      } else {
        await auth.requestOtp(`${COUNTRY_CODE}${phone}`);
        setSent(true);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const ready = !busy && phone.length === DIGITS && (!sent || code.trim().length > 0);

  const field = [styles.field, { backgroundColor: tone.surface, color: tone.ink, borderColor: tone.hairline }];

  return (
    <View style={{ flex: 1, padding: metric.gutter }}>
      <Text style={[t.meta(12, '600', 0), { color: tone.chalk }]}>
        {sent ? 'Enter the code we sent' : 'A phone number is needed to report or confirm'}
      </Text>
      <View style={[styles.field, styles.phone, { backgroundColor: tone.surface, borderColor: tone.hairline }]}>
        <Text style={[styles.prefix, { color: sent ? tone.chalk : tone.ink }]}>{COUNTRY_CODE}</Text>
        <TextInput
          ref={phoneField}
          style={[styles.digits, { color: sent ? tone.chalk : tone.ink }]}
          value={phone}
          onChangeText={(text) => setPhone(nationalNumber(text))}
          keyboardType="number-pad"
          textContentType="telephoneNumber"
          autoComplete="tel"
          placeholder="10-digit number"
          placeholderTextColor={tone.chalk}
          editable={!sent}
        />
      </View>
      {sent && (
        <TextInput
          style={field}
          value={code}
          onChangeText={setCode}
          keyboardType="number-pad"
          placeholder="SMS code"
          placeholderTextColor={tone.chalk}
        />
      )}
      {error && <Text style={[t.body(14), { color: tone.hazard, marginTop: 12 }]}>{error}</Text>}
      <Pressable
        disabled={!ready}
        onPress={submit}
        style={[styles.cta, { backgroundColor: tone.accent, opacity: ready ? 1 : 0.5 }]}>
        <Text style={[t.display(16, '600'), { color: '#000' }]}>{sent ? 'Verify' : 'Send code'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  field: {
    height: 52, borderRadius: metric.radius, borderWidth: 1,
    paddingHorizontal: 14, marginTop: 12, fontSize: 18,
  },
  phone: { flexDirection: 'row', alignItems: 'center' },
  prefix: { fontSize: 18, fontWeight: '600', marginRight: 8, fontVariant: ['tabular-nums'] },
  digits: { flex: 1, height: '100%', fontSize: 18, fontVariant: ['tabular-nums'] },
  cta: { height: 50, borderRadius: metric.radius, alignItems: 'center', justifyContent: 'center', marginTop: 24 },
});
