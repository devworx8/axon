import React from 'react';
import { StyleSheet, Text } from 'react-native';

import { SurfaceCard } from '@/components/SurfaceCard';
import { useTheme } from '@/theme/ThemeProvider';

type Props = {
  title: string;
  subtitle: string;
  detail?: string;
  deviceName?: string;
  apiBaseUrl?: string;
  error?: string | null;
};

export function CompanionOfflineGate({
  title,
  subtitle,
  detail,
  deviceName,
  apiBaseUrl,
  error,
}: Props) {
  const { colors } = useTheme();

  return (
    <SurfaceCard>
      <Text style={[styles.kicker, { color: colors.accent }]}>Axon Online</Text>
      <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
      <Text style={[styles.subtitle, { color: colors.muted }]}>{subtitle}</Text>
      {detail ? <Text style={[styles.detail, { color: colors.muted }]}>{detail}</Text> : null}
      <Text style={[styles.status, { color: colors.text }]}>
        This phone is still trusted. Axon will reconnect automatically when the desktop runtime comes back online.
      </Text>
      {deviceName ? <Text style={[styles.meta, { color: colors.muted }]}>Device: {deviceName}</Text> : null}
      {apiBaseUrl ? <Text style={[styles.meta, { color: colors.muted }]}>Desktop URL: {apiBaseUrl}</Text> : null}
      {error ? <Text style={[styles.error, { color: colors.warning }]}>{error}</Text> : null}
    </SurfaceCard>
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
  status: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '600',
  },
  meta: {
    fontSize: 12,
    lineHeight: 18,
  },
  error: {
    fontSize: 12,
    lineHeight: 18,
  },
});
