import React from 'react';
import { StyleSheet, Text } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { CompanionSession } from '@/types/companion';

export function SessionScreen({ session }: { session: CompanionSession | null }) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Session" subtitle="Resume the last active companion thread." />
      {session ? (
        <Text style={styles.detail}>{session.summary || session.active_task || session.session_key}</Text>
      ) : (
        <Text style={styles.empty}>No active companion session yet.</Text>
      )}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  detail: {
    color: '#e5eefb',
    fontSize: 13,
    lineHeight: 19,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});

