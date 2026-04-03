import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme/ThemeProvider';

export function StatusPill({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'ok' | 'warn' | 'danger' }) {
  const { colors } = useTheme();
  const stylesByTone = {
    neutral: { backgroundColor: '#162235', borderColor: colors.border, color: colors.text },
    ok: { backgroundColor: '#10271d', borderColor: '#1d4d3b', color: colors.success },
    warn: { backgroundColor: '#2d2310', borderColor: '#6b4f13', color: colors.warning },
    danger: { backgroundColor: '#2b141d', borderColor: '#742234', color: colors.danger },
  }[tone];

  return (
    <View style={[styles.pill, { backgroundColor: stylesByTone.backgroundColor, borderColor: stylesByTone.borderColor }]}>
      <Text style={[styles.text, { color: stylesByTone.color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  text: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
});

