import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme/ThemeProvider';

export function MetricCard({
  label,
  value,
  accent = 'neutral',
}: {
  label: string;
  value: string | number;
  accent?: 'neutral' | 'accent' | 'success' | 'warn';
}) {
  const { colors } = useTheme();
  const accentColor = {
    neutral: colors.text,
    accent: colors.accent,
    success: colors.success,
    warn: colors.warning,
  }[accent];

  return (
    <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Text style={[styles.label, { color: colors.muted }]}>{label}</Text>
      <Text style={[styles.value, { color: accentColor }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    minWidth: 0,
    borderWidth: 1,
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 14,
    gap: 6,
  },
  label: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.7,
    textTransform: 'uppercase',
  },
  value: {
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: -0.4,
  },
});
