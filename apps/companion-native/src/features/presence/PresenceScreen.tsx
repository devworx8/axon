import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { CompanionPresence } from '@/types/companion';

export function PresenceScreen({ presence }: { presence: CompanionPresence | null }) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Presence" subtitle="Where Axon should resume, speak, and keep listening." />
      {presence ? (
        <View style={styles.stack}>
          <StatusPill label={presence.presence_state || 'online'} tone="ok" />
          <View style={styles.metrics}>
            <MetricCard label="Workspace" value={presence.workspace_id ?? 'None'} accent="accent" />
            <MetricCard label="Voice" value={presence.voice_state || 'idle'} />
          </View>
          <Text style={styles.line}>Workspace {presence.workspace_id ?? 'none'}</Text>
          <Text style={styles.line}>Voice mode {presence.voice_state || 'idle'}</Text>
          <Text style={styles.line}>Route {presence.active_route || 'home'}</Text>
        </View>
      ) : (
        <Text style={styles.empty}>No device presence yet.</Text>
      )}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 8,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  line: {
    color: '#dbe7f7',
    fontSize: 13,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});
