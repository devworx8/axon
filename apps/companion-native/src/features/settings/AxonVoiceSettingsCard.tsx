import React from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import Slider from '@react-native-community/slider';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import type { AxonModeStatus } from '@/types/axon';
import type { CompanionSettings } from './useSettings';

const PROVIDER_OPTIONS = [
  { key: 'cloud', label: 'Cloud' },
  { key: 'local', label: 'Local' },
  { key: 'device', label: 'Device' },
] as const;

export function AxonVoiceSettingsCard({
  settings,
  axonStatus,
  onToggleVoice,
  onToggleListening,
  onToggleSpokenReplies,
  onToggleAxonMode,
  onChangeAxonWakePhrase,
  onToggleAxonBootSound,
  onToggleContinuousForegroundMonitoring,
  onChangeAxonVoiceProvider,
  onChangeAxonVoiceIdentity,
  onChangeAzureSpeechKey,
  onChangeAzureSpeechRegion,
  onChangeVoiceSpeechRate,
  onChangeVoiceSpeechPitch,
}: {
  settings: CompanionSettings;
  axonStatus?: AxonModeStatus | null;
  onToggleVoice: (value: boolean) => void;
  onToggleListening: (value: boolean) => void;
  onToggleSpokenReplies: (value: boolean) => void;
  onToggleAxonMode: (value: boolean) => void;
  onChangeAxonWakePhrase: (value: string) => void;
  onToggleAxonBootSound: (value: boolean) => void;
  onToggleContinuousForegroundMonitoring: (value: boolean) => void;
  onChangeAxonVoiceProvider: (value: 'cloud' | 'local' | 'device') => void;
  onChangeAxonVoiceIdentity: (value: string) => void;
  onChangeAzureSpeechKey: (value: string) => void;
  onChangeAzureSpeechRegion: (value: string) => void;
  onChangeVoiceSpeechRate: (value: string) => void;
  onChangeVoiceSpeechPitch: (value: string) => void;
}) {
  const provider = String(axonStatus?.voice_provider || settings.axonVoiceProvider || 'cloud').toLowerCase();
  const providerReady = axonStatus?.voice_provider_ready ?? false;
  const providerDetail = String(
    axonStatus?.voice_provider_detail
    || (provider === 'cloud' ? 'Azure speech ready' : provider === 'local' ? 'Local synthesis ready' : 'Device speech fallback')
  );
  const voiceIdentity = String(axonStatus?.voice_identity_label || settings.axonVoiceIdentity || settings.axonWakePhrase || 'Axon');
  const readinessTone = providerReady ? 'ok' : 'warn';

  return (
    <SurfaceCard>
      <View style={styles.headerRow}>
        <SurfaceHeader title="Axon voice core" subtitle="Arm the voice loop, wake phrase, and reply path for this device." />
        <StatusPill label={providerReady ? 'Voice ready' : 'Setup needed'} tone={readinessTone} />
      </View>
      <View style={styles.hudRow}>
        <View style={styles.hudRing}>
          <View style={styles.hudRingInner}>
            <Text style={styles.hudLabel}>AXON VOICE</Text>
            <Text style={styles.hudValue}>{providerReady ? 'READY' : 'DEGRADED'}</Text>
            <Text style={styles.hudDetail}>{providerDetail}</Text>
          </View>
        </View>
        <View style={styles.hudStack}>
          <Text style={styles.hudSection}>Signal</Text>
          <Text style={styles.hudLine}>{provider.toUpperCase()}</Text>
          <Text style={styles.hudSection}>Identity</Text>
          <Text style={styles.hudLine}>{voiceIdentity || 'Axon'}</Text>
          <Text style={styles.hudSection}>Wake phrase</Text>
          <Text style={styles.hudLine}>{settings.axonWakePhrase || 'Axon'}</Text>
        </View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.metricsScroll}>
        <View style={styles.metricTile}><MetricCard label="Voice" value={settings.voiceEnabled ? 'On' : 'Off'} accent={settings.voiceEnabled ? 'success' : 'neutral'} /></View>
        <View style={styles.metricTile}><MetricCard label="Mode" value={settings.alwaysListening ? 'Live' : 'Push'} accent={settings.alwaysListening ? 'accent' : 'neutral'} /></View>
        <View style={styles.metricTile}><MetricCard label="Replies" value={settings.spokenReplies ? 'Spoken' : 'Silent'} accent={settings.spokenReplies ? 'accent' : 'neutral'} /></View>
        <View style={styles.metricTile}><MetricCard label="Axon mode" value={settings.axonModeEnabled ? 'Enabled' : 'Disabled'} accent={settings.axonModeEnabled ? 'success' : 'neutral'} /></View>
      </ScrollView>
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
        placeholder="Voice identity, e.g. en-ZA-LukeNeural"
        placeholderTextColor="#7b8aa3"
        autoCapitalize="none"
        autoCorrect={false}
        style={styles.input}
      />
      <View style={styles.stack}>
        <Text style={styles.sectionLabel}>Azure speech credentials</Text>
        <TextInput
          value={settings.azureSpeechKey}
          onChangeText={onChangeAzureSpeechKey}
          placeholder="Azure Speech API key"
          placeholderTextColor="#7b8aa3"
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          style={styles.input}
        />
        <TextInput
          value={settings.azureSpeechRegion}
          onChangeText={onChangeAzureSpeechRegion}
          placeholder="Azure region, e.g. eastus"
          placeholderTextColor="#7b8aa3"
          autoCapitalize="none"
          autoCorrect={false}
          style={styles.input}
        />
      </View>
      <View style={styles.stack}>
        <Text style={styles.sectionLabel}>Speech tuning</Text>
        <View style={styles.sliderRow}>
          <Text style={styles.sliderLabel}>Rate</Text>
          <View style={styles.sliderTrack}>
            <Slider
              minimumValue={0.5}
              maximumValue={1.5}
              step={0.05}
              value={parseFloat(settings.voiceSpeechRate) || 0.85}
              onSlidingComplete={(v: number) => onChangeVoiceSpeechRate(v.toFixed(2))}
              minimumTrackTintColor="#38bdf8"
              maximumTrackTintColor="#22304a"
              thumbTintColor="#7dd3fc"
            />
          </View>
          <Text style={styles.sliderValue}>{settings.voiceSpeechRate || '0.85'}</Text>
        </View>
        <View style={styles.sliderRow}>
          <Text style={styles.sliderLabel}>Pitch</Text>
          <View style={styles.sliderTrack}>
            <Slider
              minimumValue={0.5}
              maximumValue={1.5}
              step={0.05}
              value={parseFloat(settings.voiceSpeechPitch) || 1.04}
              onSlidingComplete={(v: number) => onChangeVoiceSpeechPitch(v.toFixed(2))}
              minimumTrackTintColor="#38bdf8"
              maximumTrackTintColor="#22304a"
              thumbTintColor="#7dd3fc"
            />
          </View>
          <Text style={styles.sliderValue}>{settings.voiceSpeechPitch || '1.04'}</Text>
        </View>
      </View>
      <Text style={styles.helper}>
        Cloud is the primary Axon voice when Azure speech is configured. Local uses Axon&apos;s synthesis backend. Device is the last-resort on-phone fallback.
      </Text>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  headerRow: {
    gap: 10,
  },
  hudRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 16,
    alignItems: 'center',
  },
  hudRing: {
    width: 140,
    height: 140,
    borderRadius: 70,
    borderWidth: 1,
    borderColor: '#2a3a57',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0b1627',
    shadowColor: '#38bdf8',
    shadowOpacity: 0.25,
    shadowRadius: 12,
  },
  hudRingInner: {
    width: 110,
    height: 110,
    borderRadius: 55,
    borderWidth: 1,
    borderColor: '#1d4a66',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 10,
    gap: 4,
  },
  hudLabel: {
    fontSize: 10,
    letterSpacing: 1.4,
    color: '#7dd3fc',
    textTransform: 'uppercase',
    fontWeight: '700',
  },
  hudValue: {
    fontSize: 16,
    fontWeight: '800',
    color: '#e5eefb',
    letterSpacing: 1.4,
  },
  hudDetail: {
    fontSize: 10,
    color: '#94a3b8',
    textAlign: 'center',
  },
  hudStack: {
    flex: 1,
    gap: 8,
  },
  hudSection: {
    fontSize: 10,
    color: '#7dd3fc',
    textTransform: 'uppercase',
    letterSpacing: 1.1,
    fontWeight: '700',
  },
  hudLine: {
    fontSize: 14,
    color: '#e5eefb',
    fontWeight: '700',
  },
  metricsScroll: {
    gap: 10,
    paddingVertical: 4,
  },
  metricTile: {
    minWidth: 150,
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
  sliderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  sliderLabel: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '700',
    width: 38,
  },
  sliderTrack: {
    flex: 1,
  },
  sliderValue: {
    color: '#7dd3fc',
    fontSize: 12,
    fontWeight: '800',
    width: 36,
    textAlign: 'right',
  },
});
