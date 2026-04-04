import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { useTheme } from '@/theme/ThemeProvider';
import { CompanionLiveSnapshot } from '@/types/companion';

export function LiveOperatorCard({
  snapshot,
  error,
}: {
  snapshot: CompanionLiveSnapshot | null;
  error?: string | null;
}) {
  const { colors } = useTheme();
  const operator = snapshot?.operator || null;
  const focus = snapshot?.focus || null;
  const workspace = focus?.workspace || null;

  return (
    <SurfaceCard>
      <SurfaceHeader title="Axon Live" subtitle="What live Axon is doing right now across your desktop and mobile surfaces." />
      {error ? <Text style={[styles.error, { color: colors.danger }]}>{error}</Text> : null}
      <View style={styles.statusRow}>
        <StatusPill label={operator?.active ? 'Live' : 'Standing by'} tone={operator?.active ? 'ok' : 'neutral'} />
        {operator?.phase ? <StatusPill label={operator.phase} tone={operator.active ? 'accent' : 'neutral'} /> : null}
      </View>
      <View style={styles.metrics}>
        <MetricCard label="Workspace" value={workspace?.name || operator?.workspace_name || 'Global'} accent="accent" />
        <MetricCard label="Mode" value={operator?.mode || 'idle'} accent={operator?.active ? 'success' : 'neutral'} />
      </View>
      <Text style={[styles.title, { color: colors.text }]}>{operator?.title || 'Axon is ready'}</Text>
      <Text style={[styles.detail, { color: colors.muted }]}>
        {operator?.detail || operator?.summary || 'Pair the app and Axon will mirror live operator progress here.'}
      </Text>
      {workspace?.path ? (
        <Text style={[styles.meta, { color: colors.muted }]}>Path: {workspace.path}</Text>
      ) : null}
      {workspace?.git_branch ? (
        <Text style={[styles.meta, { color: colors.muted }]}>Branch: {workspace.git_branch}</Text>
      ) : null}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  statusRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  title: {
    fontSize: 18,
    fontWeight: '800',
  },
  detail: {
    fontSize: 13,
    lineHeight: 19,
  },
  meta: {
    fontSize: 12,
  },
  error: {
    fontSize: 12,
    lineHeight: 18,
  },
});
