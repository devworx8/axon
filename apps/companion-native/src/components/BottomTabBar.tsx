import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/theme/ThemeProvider';

type TabKey = 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings';

const TAB_ITEMS: { id: TabKey; label: string; icon: string }[] = [
  { id: 'mission', label: 'Dashboard', icon: '✦' },
  { id: 'voice', label: 'Voice', icon: '🎙' },
  { id: 'attention', label: 'Alerts', icon: '⚡' },
  { id: 'sessions', label: 'Sessions', icon: '▶' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
];

export function BottomTabBar({
  activeTab,
  onTabPress,
  urgentCount = 0,
}: {
  activeTab: TabKey;
  onTabPress: (tab: TabKey) => void;
  urgentCount?: number;
}) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.bar,
        {
          backgroundColor: colors.glass,
          borderTopColor: colors.border,
          paddingBottom: Math.max(insets.bottom, 4),
        },
      ]}
    >
      {TAB_ITEMS.map((item) => {
        const active = activeTab === item.id;
        return (
          <Pressable
            key={item.id}
            style={styles.tab}
            onPress={() => onTabPress(item.id)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={item.label}
          >
            <View style={styles.tabInner}>
              <Text style={[styles.tabIcon, active && { color: colors.accent }]}>
                {item.icon}
              </Text>
              <Text
                style={[
                  styles.tabLabel,
                  { color: active ? colors.accent : colors.muted },
                ]}
              >
                {item.label}
              </Text>
              {active && (
                <View style={[styles.activeIndicator, { backgroundColor: colors.accent }]} />
              )}
              {item.id === 'attention' && urgentCount > 0 && (
                <View style={[styles.badge, { backgroundColor: colors.danger }]}>
                  <Text style={styles.badgeText}>
                    {urgentCount > 9 ? '9+' : urgentCount}
                  </Text>
                </View>
              )}
            </View>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    paddingTop: 6,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 52,
  },
  tabInner: {
    alignItems: 'center',
    gap: 2,
  },
  tabIcon: {
    fontSize: 16,
    color: '#64748b',
  },
  tabLabel: {
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  activeIndicator: {
    width: 4,
    height: 4,
    borderRadius: 2,
    marginTop: 2,
  },
  badge: {
    position: 'absolute',
    top: -4,
    right: -10,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    paddingHorizontal: 4,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: {
    color: '#fff',
    fontSize: 9,
    fontWeight: '800',
  },
});
