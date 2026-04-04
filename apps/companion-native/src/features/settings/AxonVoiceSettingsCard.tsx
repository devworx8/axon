import React from 'react';
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import type { CompanionSettings } from './useSettings';

const PROVIDER_OPTIONS = [
  { key: 'cloud', label: 'Cloud' },
  { key: 'local', label: 'Local' },
  { key: 'device', label: 'Device' },
] as const;

export function AxonVoiceSettingsCard({
  settings,
  onToggleVoice,
  onToggleListening,
  onToggleSpokenReplies,
  onToggleAxonMode,
  onChangeAxonWakePhrase,
  onToggleAxonBootSound,
  onToggleContinuousForegroundMonitoring,
  onChangeAxonVoiceProvider,
  onChangeAxonVoiceIdentity,
}: {
  settings: CompanionSettings;
  onToggleVoice: (value: boolean) => void;
  onToggleListening: (value: boolean) => void;
  onToggleSpokenReplies: (value: boolean) => void;
  onToggleAxonMode: (value: boolean) => void;
  onChangeAxonWakePhrase: (value: string) => void;
  onToggleAxonBootSound: (value: boolean) => void;
  onToggleContinuousForegroundMonitoring: (value: boolean) => void;
  onChangeAxonVoiceProvider: (value: 'cloud' | 'local' | 'device') => void;
  onChangeAxonVoiceIdentity: (value: string) => void;
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Axon voice" subtitle="Tune the armed Axon experience, wake phrase, and reply identity for this device." />
      <View style={styles.metrics}>
        <MetricCard label="Voice" value={settings.voiceEnabled ? 'On' : 'Off'} accent={settings.voiceEnabled ? 'success' : 'neutral'} />
        <MetricCard label="Voice mode" value={settings.alwaysListening ? 'Live' : 'Push'} accent={settings.alwaysListening ? 'accent' : 'neutral'} />
        <MetricCard label="Replies" value={settings.spokenReplies ? 'Spoken' : 'Silent'} accent={settings.spokenReplies ? 'accent' : 'neutral'} />
        <MetricCard label="Axon mode" value={settings.axonModeEnabled ? 'Enabled' : 'Disabled'} accent={settings.axonModeEnabled ? 'success' : 'neutral'} />
        <MetricCard label="Reply path" value={String(settings.axonVoiceProvider || 'cloud').toUpperCase()} accent="accent" />
        <MetricCard label="Wake phrase" value={settings.axonWakePhrase || 'Axon'} accent="accent" />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Voice enabled</Text>
        <Switch value={settings.voiceEnabled} onValueChange={onToggleVoice} />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Live voice mode</Text>
        <Switch value={settings.alwaysListening} onValueChange={onToggleListening} />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Speak Axon replies aloud</Text>
        <Switch value={settings.spokenReplies} onValueChange={onToggleSpokenReplies} />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Enable Axon mode</Text>
        <Switch value={settings.axonModeEnabled} onValueChange={onToggleAxonMode} />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Robot boot sound</Text>
        <Switch value={settings.axonBootSound} onValueChange={onToggleAxonBootSound} />
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Continuous foreground monitoring</Text>
        <Switch value={settings.continuousForegroundMonitoring} onValueChange={onToggleContinuousForegroundMonitoring} />
      </View>
      <View style={styles.stack}>
        <Text style={styles.sectionLabel}>Reply provider</Text>
        <View style={styles.providerRow}>
          {PROVIDER_OPTIONS.map((option) => {
            const active = settings.axonVoiceProvider === option.key;
            return (
              <Pressable
                key={option.key}
                onPress={() => onChangeAxonVoiceProvider(option.key)}
                style={[styles.providerChip, active ? styles.providerChipActive : null]}
              >
                <Text style={[styles.providerText, active ? styles.providerTextActive : null]}>{option.label}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>
      <TextInput
        value={settings.axonWakePhrase}
        onChangeText={onChangeAxonWakePhrase}
        placeholder="Wake phrase"
        placeholderTextColor="#7b8aa3"
        autoCapitalize="words"
        autoCorrect={false}
        style={styles.input}
      />
      <TextInput
        value={settings.axonVoiceIdentity}
        onChangeText={onChangeAxonVoiceIdentity}
        placeholder="Voice identity, e.g. en-ZA-LeahNeural"
        placeholderTextColor="#7b8aa3"
        autoCapitalize="none"
        autoCorrect={false}
        style={styles.input}
      />
      <Text style={styles.helper}>
        Cloud is the primary Axon voice when Azure speech is configured. Local uses Axon&apos;s synthesis backend. Device is the last-resort on-phone fallback.
      </Text>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  stack: {
    gap: 8,
  },
  label: {
    color: '#e5eefb',
    fontSize: 13,
  },
  sectionLabel: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  providerRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  providerChip: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#0b1627',
  },
  providerChipActive: {
    borderColor: '#38bdf8',
    backgroundColor: '#102235',
  },
  providerText: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '700',
  },
  providerTextActive: {
    color: '#7dd3fc',
  },
  input: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#e5eefb',
    backgroundColor: '#0b1627',
    fontSize: 12,
  },
  helper: {
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 18,
  },
});
