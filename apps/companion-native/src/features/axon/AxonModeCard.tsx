import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import type { AxonModeStatus } from '@/types/companion';
import { isVoiceTranscriptionReady } from '@/features/voice/voiceReadiness';
import { AxonHudDial } from './AxonHudDial';

function toneForState(state: string): 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' {
  if (state === 'engaged') return 'accent';
  if (state === 'degraded') return 'warn';
  if (state === 'armed' || state === 'listening') return 'ok';
  return 'neutral';
}

function formatStamp(value?: string) {
  if (!value) {
    return 'Never';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function AxonModeCard({
  axon,
  wakePhrase,
  onChangeWakePhrase,
  busy,
  error,
  onArm,
  onDisarm,
}: {
  axon?: AxonModeStatus | null;
  wakePhrase: string;
  onChangeWakePhrase: (value: string) => void;
  busy?: boolean;
  error?: string | null;
  onArm?: () => void;
  onDisarm?: () => void;
}) {
  const monitoringState = String(axon?.monitoring_state || 'idle');
  const voiceReady = isVoiceTranscriptionReady(axon);
  const providerLabel = String(
    axon?.voice_identity_label
    || axon?.voice_identity
    || axon?.voice_provider
    || 'speech route pending',
  ).trim();

  return (
    <SurfaceCard>
      <SurfaceHeader
        title="Axon Mode"
        subtitle="Foreground sentinel mode listens for your wake phrase, then routes the next spoken command through the live Axon control path."
      />
      <AxonHudDial state={monitoringState} wakePhrase={wakePhrase} providerLabel={providerLabel} />
      <View style={styles.pills}>
        <StatusPill label={axon?.armed ? 'Armed' : 'Standby'} tone={axon?.armed ? 'ok' : 'neutral'} />
        <StatusPill label={monitoringState.replace('_', ' ')} tone={toneForState(monitoringState)} />
        <StatusPill label={axon?.foreground_only ? 'Foreground only' : 'Unknown scope'} tone="accent" />
      </View>
      <View style={styles.metrics}>
        <MetricCard label="Wake phrase" value={wakePhrase || 'Axon'} accent="accent" />
        <MetricCard label="Voice" value={voiceReady ? 'Ready' : 'Blocked'} accent={voiceReady ? 'success' : 'warn'} />
        <MetricCard label="Reply path" value={String(axon?.voice_provider || 'unavailable').toUpperCase()} accent={axon?.voice_provider_ready ? 'accent' : 'warn'} />
        <MetricCard label="Last wake" value={formatStamp(axon?.last_wake_at)} accent={axon?.last_wake_at ? 'accent' : 'neutral'} />
      </View>
      <TextInput
        value={wakePhrase}
        onChangeText={onChangeWakePhrase}
        placeholder="Wake phrase"
        placeholderTextColor="#7b8aa3"
        autoCapitalize="words"
        autoCorrect={false}
        style={styles.input}
      />
      <Text style={styles.summary}>
        {axon?.summary || 'Arm Axon mode to start the foreground monitoring loop.'}
      </Text>
      {axon?.voice_provider_detail ? (
        <View style={styles.callout}>
          <Text style={styles.calloutLabel}>Reply voice</Text>
          <Text style={styles.calloutText}>{axon.voice_provider_detail}</Text>
        </View>
      ) : null}
      {axon?.last_command_text ? (
        <View style={styles.callout}>
          <Text style={styles.calloutLabel}>Last command</Text>
          <Text style={styles.calloutText}>{axon.last_command_text}</Text>
        </View>
      ) : null}
      {axon?.degraded_reason ? (
        <View style={styles.callout}>
          <Text style={styles.calloutLabel}>Why it paused</Text>
          <Text style={styles.calloutText}>{axon.degraded_reason}</Text>
        </View>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.actions}>
        {axon?.armed ? (
          <Pressable onPress={onDisarm} disabled={busy} style={[styles.primaryAction, busy ? styles.disabled : null]}>
            <Text style={styles.primaryText}>{busy ? 'Working…' : 'Disarm Axon'}</Text>
          </Pressable>
        ) : (
          <Pressable
            onPress={onArm}
            disabled={busy || !voiceReady}
            style={[styles.primaryAction, (busy || !voiceReady) ? styles.disabled : null]}
          >
            <Text style={styles.primaryText}>{busy ? 'Arming…' : 'Arm Axon'}</Text>
          </Pressable>
        )}
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
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
  summary: {
    color: '#cbd5e1',
    fontSize: 13,
    lineHeight: 19,
  },
  callout: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 4,
    backgroundColor: '#0b1627',
  },
  calloutLabel: {
    color: '#7dd3fc',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  calloutText: {
    color: '#e5eefb',
    fontSize: 13,
    lineHeight: 19,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryAction: {
    borderRadius: 14,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  primaryText: {
    color: '#08111f',
    fontWeight: '800',
  },
  disabled: {
    opacity: 0.6,
  },
  error: {
    color: '#fda4af',
    fontSize: 12,
    lineHeight: 18,
  },
});
