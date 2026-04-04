import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  apiBaseUrl: string;
  onChangeApiBaseUrl: (value: string) => void;
  deviceName: string;
  onChangeDeviceName: (value: string) => void;
  pairingPin: string;
  onChangePairingPin: (value: string) => void;
  onPair: () => void;
  pairing?: boolean;
  error?: string | null;
};

export function AuthScreen({ apiBaseUrl, onChangeApiBaseUrl, deviceName, onChangeDeviceName, pairingPin, onChangePairingPin, onPair, pairing, error }: Props) {
  const { colors } = useTheme();
  return (
    <SurfaceCard>
      <SurfaceHeader title="Device auth" subtitle="Pair this phone with Axon Online and resume live sessions securely." />
      <View style={styles.row}>
        <StatusPill label="Axon Online" tone="ok" />
        <StatusPill label="Native" tone="neutral" />
      </View>
      <View style={styles.metrics}>
        <MetricCard label="Device" value={deviceName || 'Phone'} accent="accent" />
        <MetricCard label="Pairing" value={pairing ? 'Working' : 'Ready'} accent={pairing ? 'warn' : 'success'} />
      </View>
      <TextInput
        value={apiBaseUrl}
        onChangeText={onChangeApiBaseUrl}
        placeholder="Axon desktop URL, e.g. http://192.168.1.50:7734"
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        style={[styles.input, { borderColor: colors.border, color: colors.text, backgroundColor: '#0b1627' }]}
      />
      <TextInput
        value={deviceName}
        onChangeText={onChangeDeviceName}
        placeholder="My phone"
        placeholderTextColor={colors.muted}
        style={[styles.input, { borderColor: colors.border, color: colors.text, backgroundColor: '#0b1627' }]}
      />
      <TextInput
        value={pairingPin}
        onChangeText={onChangePairingPin}
        placeholder="Axon PIN"
        placeholderTextColor={colors.muted}
        secureTextEntry
        style={[styles.input, { borderColor: colors.border, color: colors.text, backgroundColor: '#0b1627' }]}
      />
      <Pressable onPress={onPair} style={({ pressed }) => [styles.button, { opacity: pressed ? 0.8 : 1 }]}>
        <Text style={styles.buttonText}>{pairing ? 'Pairing...' : 'Pair device'}</Text>
      </Pressable>
      {error ? <Text style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: 8,
    flexWrap: 'wrap',
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  input: {
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  button: {
    borderRadius: 14,
    paddingVertical: 12,
    alignItems: 'center',
    backgroundColor: '#38bdf8',
  },
  buttonText: {
    color: '#08111f',
    fontWeight: '800',
  },
  error: {
    fontSize: 12,
  },
});
