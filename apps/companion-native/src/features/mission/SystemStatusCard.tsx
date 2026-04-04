import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { PlatformSystemStatus } from '@/types/companion';

export function SystemStatusCard({
  systems,
}: {
  systems?: PlatformSystemStatus[];
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Systems strip" subtitle="GitHub, CI/CD, Vercel, Sentry, runtime, preview, and task orchestration at a glance." />
      <View style={styles.stack}>
        {(systems || []).map((system) => (
          <View key={system.key} style={styles.row}>
            <View style={styles.meta}>
              <Text style={styles.title}>{system.label}</Text>
              <Text style={styles.detail}>{system.summary || 'No current summary.'}</Text>
            </View>
            <View style={styles.pills}>
              <StatusPill
                label={system.status}
                tone={system.urgent ? 'danger' : system.status === 'attention' ? 'warn' : system.status === 'linked' || system.status === 'connected' || system.status === 'live' ? 'ok' : 'neutral'}
              />
              {system.linked ? <StatusPill label="Linked" tone="accent" /> : null}
            </View>
          </View>
        ))}
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 10,
  },
  row: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 8,
    backgroundColor: '#0b1627',
  },
  meta: {
    gap: 4,
  },
  title: {
    color: '#e5eefb',
    fontSize: 14,
    fontWeight: '800',
  },
  detail: {
    color: '#7f93ad',
    fontSize: 12,
    lineHeight: 18,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
});
