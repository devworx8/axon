import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { ControlCapability, PlatformSnapshot } from '@/types/companion';

type QuickActionItem = NonNullable<PlatformSnapshot['quick_actions']>[number];

function isBusy(busyActionType: string | null, actionType: string) {
  return busyActionType === actionType || busyActionType === `confirm:${actionType}`;
}

export function QuickActionsCard({
  quickActions,
  capabilities,
  busyActionType,
  onExecuteAction,
  onApprovePending,
  onOpenVoice,
  onOpenProjects,
  onOpenAttention,
  onOpenSessions,
}: {
  quickActions?: QuickActionItem[];
  capabilities?: ControlCapability[];
  busyActionType?: string | null;
  onExecuteAction: (actionType: string) => void;
  onApprovePending?: () => void;
  onOpenVoice: () => void;
  onOpenProjects: () => void;
  onOpenAttention: () => void;
  onOpenSessions: () => void;
}) {
  const capabilityMap = new Map((capabilities || []).map((item) => [item.action_type, item]));
  const suggested = (quickActions || [])
    .filter((item) => item.available !== false)
    .slice(0, 3);
  const builtIns = [
    { key: 'talk', label: 'Talk to Axon', tone: 'accent' as const, onPress: onOpenVoice },
    { key: 'approve', label: 'Approve pending', tone: 'warn' as const, onPress: onApprovePending || onOpenSessions },
    { key: 'projects', label: 'Open projects', tone: 'neutral' as const, onPress: onOpenProjects },
    { key: 'attention', label: 'Review attention', tone: 'warn' as const, onPress: onOpenAttention },
    { key: 'sessions', label: 'Open sessions', tone: 'ok' as const, onPress: onOpenSessions },
  ];

  return (
    <SurfaceCard>
      <SurfaceHeader title="Quick actions" subtitle="Start Axon fast, then jump into the deeper screens only when needed." />
      <View style={styles.row}>
        {builtIns.map((item) => (
          <Pressable key={item.key} onPress={item.onPress} style={styles.primaryAction}>
            <Text style={styles.primaryActionText}>{item.label}</Text>
          </Pressable>
        ))}
      </View>
      {suggested.length ? (
        <View style={styles.suggested}>
          <Text style={styles.suggestedTitle}>Suggested next moves</Text>
          {suggested.map((action) => {
            const capability = capabilityMap.get(action.action_type);
            const available = action.available !== false && capability?.available !== false;
            const planned = Boolean(action.planned);
            const busy = isBusy(busyActionType || null, action.action_type);
            return (
              <Pressable
                key={action.action_type}
                onPress={() => onExecuteAction(action.action_type)}
                disabled={!available || busy}
                style={[
                  styles.suggestedRow,
                  (!available || busy) ? styles.actionChipDisabled : null,
                ]}
              >
                <View style={styles.suggestedText}>
                  <Text style={styles.actionChipText}>{busy ? 'Working…' : (action.label || action.action_type)}</Text>
                  <Text style={styles.actionChipSub}>Tap to run in the active workspace.</Text>
                </View>
                <View style={styles.metaRow}>
                  {action.risk_tier ? <StatusPill label={String(action.risk_tier)} tone={action.risk_tier === 'destructive' ? 'danger' : 'neutral'} /> : null}
                  {planned ? <StatusPill label="Planned" tone="warn" /> : null}
                </View>
              </Pressable>
            );
          })}
        </View>
      ) : null}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryAction: {
    borderRadius: 14,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  primaryActionText: {
    color: '#08111f',
    fontWeight: '800',
  },
  suggested: {
    marginTop: 14,
    gap: 8,
  },
  suggestedTitle: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  suggestedRow: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 10,
    backgroundColor: '#0b1627',
  },
  suggestedText: {
    gap: 4,
  },
  actionChipDisabled: {
    opacity: 0.6,
  },
  actionChipText: {
    color: '#e5eefb',
    fontSize: 13,
    fontWeight: '800',
  },
  actionChipSub: {
    color: '#7f93ad',
    fontSize: 12,
    lineHeight: 17,
  },
  metaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
});
