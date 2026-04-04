import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { useTheme } from '@/theme/ThemeProvider';
import { PlatformSnapshot } from '@/types/companion';

function trustLabel(snapshot: PlatformSnapshot | null) {
  const trust = snapshot?.trust;
  if (!trust) return 'Untrusted';
  if (trust.challenge_required) return 'Challenge required';
  if (trust.elevation?.active) return `Elevated · ${trust.effective_max_risk_tier || 'act'}`;
  return `Trusted · ${trust.effective_max_risk_tier || 'act'}`;
}

function trustTone(snapshot: PlatformSnapshot | null): 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' {
  const trust = snapshot?.trust;
  if (!trust) return 'warn';
  if (trust.challenge_required) return 'danger';
  if (trust.elevation?.active) return 'ok';
  return 'accent';
}

export function MissionHeroCard({
  snapshot,
  digest,
  loading,
  onRefresh,
}: {
  snapshot: PlatformSnapshot | null;
  digest?: string;
  loading?: boolean;
  onRefresh?: () => void;
}) {
  const { colors } = useTheme();
  const posture = String(snapshot?.posture || 'healthy').replace('_', ' ');
  const focus = snapshot?.focus?.workspace;
  const focusPreview = snapshot?.focus?.preview as Record<string, unknown> | null | undefined;
  const operator = snapshot?.live?.operator;
  const counts = snapshot?.attention?.summary?.counts || {};
  const nextRequired = snapshot?.next_required_action as Record<string, unknown> | null | undefined;
  const latestOutcome = snapshot?.latest_command_outcome;

  return (
    <SurfaceCard>
      <SurfaceHeader
        title="Mission Control"
        subtitle="Your live Axon operator cockpit. Read the platform, issue commands, and handle protected actions from one place."
      />
      <View style={styles.postureRow}>
        <StatusPill label={posture} tone={posture === 'urgent' ? 'danger' : posture === 'degraded' ? 'warn' : 'ok'} />
        <StatusPill label={trustLabel(snapshot)} tone={trustTone(snapshot)} />
        {focus?.name ? <StatusPill label={focus.name} tone="accent" /> : null}
      </View>
      <View style={styles.metrics}>
        <MetricCard label="Now" value={counts.now || 0} accent="warn" />
        <MetricCard label="Waiting" value={counts.waiting_on_me || 0} accent="accent" />
        <MetricCard label="Watch" value={counts.watch || 0} />
      </View>
      <View style={styles.stack}>
        <Text style={[styles.kicker, { color: colors.accent }]}>Live operator</Text>
        <Text style={[styles.primaryLine, { color: colors.text }]}>
          {operator?.title || (operator?.active ? 'Axon is actively running.' : 'Axon is standing by.')}
        </Text>
        <Text style={[styles.secondaryLine, { color: colors.muted }]}>
          {digest || operator?.detail || 'Mission digest will appear here once the first live snapshot arrives.'}
        </Text>
      </View>
      <View style={styles.stack}>
        <Text style={[styles.kicker, { color: colors.accent }]}>Focus</Text>
        <Text style={[styles.primaryLine, { color: colors.text }]}>
          {focus?.name || 'Global platform view'}
        </Text>
        <Text style={[styles.secondaryLine, { color: colors.muted }]}>
          {focus?.path || 'Choose a project to steer Axon with workspace-aware actions.'}
        </Text>
        {focusPreview?.status ? (
          <Text style={[styles.secondaryLine, { color: colors.muted }]}>
            Preview {String(focusPreview.status).replace('_', ' ')}
            {focusPreview?.url ? ` · ${String(focusPreview.url)}` : ''}
          </Text>
        ) : null}
      </View>
      {nextRequired ? (
        <View style={[styles.callout, { borderColor: colors.warning }]}>
          <Text style={[styles.calloutTitle, { color: colors.text }]}>Next required action</Text>
          <Text style={[styles.calloutBody, { color: colors.muted }]}>
            {String(nextRequired.title || nextRequired.summary || nextRequired.detail || 'Something needs your attention.')}
          </Text>
        </View>
      ) : null}
      {latestOutcome ? (
        <View style={[styles.callout, { borderColor: colors.border }]}>
          <Text style={[styles.calloutTitle, { color: colors.text }]}>Latest command outcome</Text>
          <Text style={[styles.calloutBody, { color: colors.muted }]}>
            {latestOutcome.summary || latestOutcome.title || latestOutcome.action_type}
          </Text>
        </View>
      ) : null}
      <Pressable
        onPress={onRefresh}
        disabled={!onRefresh || loading}
        style={[styles.refreshButton, loading ? styles.refreshButtonDisabled : null]}
      >
        <Text style={styles.refreshButtonText}>{loading ? 'Refreshing...' : 'Refresh Mission Control'}</Text>
      </Pressable>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  postureRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  stack: {
    gap: 4,
  },
  kicker: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  primaryLine: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  secondaryLine: {
    fontSize: 13,
    lineHeight: 19,
  },
  callout: {
    borderWidth: 1,
    borderRadius: 16,
    padding: 12,
    gap: 6,
    backgroundColor: '#0c1524',
  },
  calloutTitle: {
    fontSize: 13,
    fontWeight: '800',
  },
  calloutBody: {
    fontSize: 13,
    lineHeight: 19,
  },
  refreshButton: {
    alignSelf: 'flex-start',
    borderRadius: 14,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  refreshButtonDisabled: {
    opacity: 0.6,
  },
  refreshButtonText: {
    color: '#08111f',
    fontWeight: '800',
  },
});
