import React from 'react';
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { CompanionSettings } from './useSettings';

export function SettingsScreen({
  settings,
  onToggleVoice,
  onToggleListening,
}: {
  settings: CompanionSettings;
  onToggleVoice: (value: boolean) => void;
  onToggleListening: (value: boolean) => void;
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Settings" subtitle="Companion preferences and voice behavior." />
      <View style={styles.row}>
        <Text style={styles.label}>Voice enabled</Text>
        <Switch value={settings.voiceEnabled} onValueChange={onToggleVoice} />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Always listening</Text>
        <Switch value={settings.alwaysListening} onValueChange={onToggleListening} />
      </View>
      <Pressable style={styles.button}>
        <Text style={styles.buttonText}>Edit backend settings in Axon desktop</Text>
      </Pressable>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  label: {
    color: '#e5eefb',
    fontSize: 13,
  },
  button: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#22304a',
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  buttonText: {
    color: '#7dd3fc',
    fontSize: 12,
    fontWeight: '700',
  },
});

