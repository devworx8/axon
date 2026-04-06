import React, { type PropsWithChildren } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme/ThemeProvider';

/**
 * Glassmorphism panel matching desktop `stark-dash-panel`.
 * Rounded-2xl, slate-900 bg with subtle cyan glow border.
 */
export function SurfaceCard({ children, glow }: PropsWithChildren<{ glow?: boolean }>) {
  const { colors } = useTheme();
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: colors.glass,
          borderColor: glow ? colors.accentBorder : colors.border,
        },
        glow && styles.glowShadow,
      ]}
    >
      {children}
    </View>
  );
}

/** Matches desktop `stark-dash-header` eyebrow + title pattern. */
export function SurfaceHeader({ eyebrow, title, subtitle }: { eyebrow?: string; title: string; subtitle?: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.header}>
      {eyebrow ? (
        <Text style={[styles.eyebrow, { color: colors.muted }]}>{eyebrow}</Text>
      ) : null}
      <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
      {subtitle ? <Text style={[styles.subtitle, { color: colors.textSecondary }]}>{subtitle}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 12,
    // Approximates desktop backdrop-blur glass effect
    shadowColor: '#000',
    shadowOpacity: 0.35,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 10 },
    elevation: 8,
  },
  glowShadow: {
    shadowColor: '#22d3ee',
    shadowOpacity: 0.12,
    shadowRadius: 16,
  },
  header: {
    gap: 4,
  },
  eyebrow: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2.2,
    textTransform: 'uppercase',
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  subtitle: {
    fontSize: 13,
    lineHeight: 18,
  },
});
