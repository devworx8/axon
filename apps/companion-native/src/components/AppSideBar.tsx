import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme/ThemeProvider';

type SideNavItem = {
  key: string;
  label: string;
  hint?: string;
};

export function AppSideBar({
  items,
  activeKey,
  statusLabel,
  statusColor,
  onChange,
}: {
  items: readonly SideNavItem[];
  activeKey: string;
  statusLabel: string;
  statusColor: string;
  onChange: (key: string) => void;
}) {
  const { colors } = useTheme();

  return (
    <View style={[styles.rail, { borderRightColor: colors.border, backgroundColor: colors.surfaceAlt }]}>
      <View style={styles.brand}>
        <View style={[styles.orb, { borderColor: colors.accent, shadowColor: colors.accent }]} />
        <Text style={[styles.brandText, { color: colors.text }]}>Axon</Text>
        <Text style={[styles.brandSub, { color: colors.muted }]}>Online</Text>
      </View>

      <View style={[styles.statusPill, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
        <Text style={[styles.statusText, { color: statusColor }]}>{statusLabel}</Text>
      </View>

      <ScrollView contentContainerStyle={styles.navList} showsVerticalScrollIndicator={false}>
        {items.map((item) => {
          const active = item.key === activeKey;
          return (
            <Pressable
              key={item.key}
              onPress={() => onChange(item.key)}
              accessibilityRole="tab"
              accessibilityLabel={item.label}
              accessibilityState={{ selected: active }}
              style={[
                styles.navItem,
                {
                  borderColor: active ? 'rgba(110, 231, 255, 0.45)' : colors.border,
                  backgroundColor: active ? 'rgba(110, 231, 255, 0.12)' : colors.surface,
                },
              ]}
            >
              <Text style={[styles.navLabel, { color: active ? colors.accent : colors.text }]}>{item.label}</Text>
              {item.hint ? (
                <Text style={[styles.navHint, { color: colors.muted }]}>{item.hint}</Text>
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  rail: {
    width: 120,
    paddingTop: 20,
    paddingBottom: 16,
    paddingHorizontal: 10,
    borderRightWidth: 1,
  },
  brand: {
    alignItems: 'center',
    gap: 6,
    marginBottom: 14,
  },
  orb: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    backgroundColor: 'rgba(110, 231, 255, 0.08)',
    shadowOpacity: 0.4,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 },
  },
  brandText: {
    fontSize: 16,
    fontWeight: '800',
    letterSpacing: 0.4,
  },
  brandSub: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
    textTransform: 'uppercase',
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 6,
    alignSelf: 'center',
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 999,
  },
  statusText: {
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  navList: {
    paddingTop: 18,
    gap: 8,
  },
  navItem: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 12,
    paddingHorizontal: 10,
    gap: 4,
  },
  navLabel: {
    fontSize: 11,
    fontWeight: '800',
    textAlign: 'center',
  },
  navHint: {
    fontSize: 9,
    fontWeight: '600',
    textAlign: 'center',
    letterSpacing: 0.2,
  },
});
