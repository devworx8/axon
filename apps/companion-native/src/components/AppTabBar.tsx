import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme/ThemeProvider';

type TabItem = {
  key: string;
  label: string;
};

export function AppTabBar({
  tabs,
  activeKey,
  onChange,
}: {
  tabs: readonly TabItem[];
  activeKey: string;
  onChange: (key: string) => void;
}) {
  const { colors } = useTheme();

  return (
    <View style={styles.wrap}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.content}
      >
        {tabs.map((tab) => {
          const active = tab.key === activeKey;
          return (
            <Pressable
              key={tab.key}
              onPress={() => onChange(tab.key)}
              style={[
                styles.tab,
                {
                  borderColor: active ? 'rgba(110, 231, 255, 0.32)' : colors.border,
                  backgroundColor: active ? 'rgba(110, 231, 255, 0.12)' : colors.surface,
                },
              ]}
            >
              <Text
                style={[
                  styles.tabText,
                  { color: active ? colors.accent : colors.muted },
                ]}
              >
                {tab.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: 14,
  },
  content: {
    gap: 10,
    paddingRight: 8,
  },
  tab: {
    minHeight: 44,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 10,
    justifyContent: 'center',
  },
  tabText: {
    fontSize: 13,
    fontWeight: '700',
  },
});
