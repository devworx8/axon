import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

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
          <Text style={styles.line}>Workspace {presence.workspace_id ?? 'none'}</Text>
          <Text style={styles.line}>Voice {presence.voice_state || 'idle'}</Text>
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
  line: {
    color: '#dbe7f7',
    fontSize: 13,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});

