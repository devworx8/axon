import React from 'react';
import { StyleSheet, Text } from 'react-native';

import { SurfaceCard } from '@/components/SurfaceCard';
import { AuthScreen } from '@/features/auth/AuthScreen';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  title: string;
  subtitle: string;
  detail?: string;
  busy?: boolean;
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

export function CompanionSessionGate({
  title,
  subtitle,
  detail,
  busy,
  apiBaseUrl,
  onChangeApiBaseUrl,
  deviceName,
  onChangeDeviceName,
  pairingPin,
  onChangePairingPin,
  onPair,
  pairing,
  error,
}: Props) {
  const { colors } = useTheme();

  return (
    <>
      <SurfaceCard>
        <Text style={[styles.kicker, { color: colors.accent }]}>Axon Online</Text>
        <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.subtitle, { color: colors.muted }]}>{subtitle}</Text>
        {detail ? <Text style={[styles.detail, { color: colors.muted }]}>{detail}</Text> : null}
        {busy ? (
          <Text style={[styles.busy, { color: colors.text }]}>
            Verifying the saved mobile operator session before protected routes are enabled.
          </Text>
        ) : null}
      </SurfaceCard>
      {busy ? null : (
        <AuthScreen
          apiBaseUrl={apiBaseUrl}
          onChangeApiBaseUrl={onChangeApiBaseUrl}
          deviceName={deviceName}
          onChangeDeviceName={onChangeDeviceName}
          pairingPin={pairingPin}
          onChangePairingPin={onChangePairingPin}
          onPair={onPair}
          pairing={pairing}
          error={error}
        />
      )}
    </>
  );
}

const styles = StyleSheet.create({
  kicker: {
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 1.1,
  },
  title: {
    fontSize: 24,
    fontWeight: '800',
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 20,
  },
  detail: {
    fontSize: 13,
    lineHeight: 18,
  },
  busy: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '600',
  },
});
