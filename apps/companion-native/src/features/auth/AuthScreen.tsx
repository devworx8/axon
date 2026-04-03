import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  deviceName: string;
  onChangeDeviceName: (value: string) => void;
  pairingPin: string;
  onChangePairingPin: (value: string) => void;
  onPair: () => void;
  pairing?: boolean;
  error?: string | null;
};

export function AuthScreen({ deviceName, onChangeDeviceName, pairingPin, onChangePairingPin, onPair, pairing, error }: Props) {
  const { colors } = useTheme();
  return (
    <SurfaceCard>
      <SurfaceHeader title="Device auth" subtitle="Pair this phone with Axon and resume companion sessions securely." />
      <View style={styles.row}>
        <StatusPill label="Companion" tone="ok" />
        <StatusPill label="Native" tone="neutral" />
      </View>
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
        placeholder="Pairing PIN (optional)"
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
