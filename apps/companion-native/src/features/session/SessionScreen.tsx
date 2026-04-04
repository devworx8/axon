import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { ActionReceipt, ApprovalRequired, CompanionSession, ExpoProjectStatus, RiskChallenge } from '@/types/companion';
import { ChallengeListCard } from './ChallengeListCard';
import { ReceiptListCard } from './ReceiptListCard';
import { ExpoControlCard } from '@/features/expo/ExpoControlCard';

export function SessionScreen({
  sessions,
  session,
  expoProject,
  expoBusyActionType,
  approval,
  challenges,
  receipts,
  actingActionType,
  onOpenChallenge,
  onResume,
  onStop,
  onConfirmChallenge,
  onRejectChallenge,
  onApprovePending,
  onExpoProjectStatus,
  onExpoBuildAndroidDev,
  onExpoBuildIosDev,
  onExpoBuildList,
  onExpoPublishUpdate,
}: {
  sessions?: CompanionSession[];
  session: CompanionSession | null;
  expoProject?: ExpoProjectStatus | null;
  expoBusyActionType?: string | null;
  approval?: ApprovalRequired | null;
  challenges?: RiskChallenge[];
  receipts?: ActionReceipt[];
  actingActionType?: string | null;
  onOpenChallenge?: (challenge: RiskChallenge) => void;
  onResume?: () => void;
  onStop?: () => void;
  onConfirmChallenge?: (challenge: RiskChallenge) => void;
  onRejectChallenge?: (challengeId: number) => void;
  onApprovePending?: () => void;
  onExpoProjectStatus?: (workspaceId: number | null) => void;
  onExpoBuildAndroidDev?: (workspaceId: number | null) => void;
  onExpoBuildIosDev?: (workspaceId: number | null) => void;
  onExpoBuildList?: (workspaceId: number | null) => void;
  onExpoPublishUpdate?: (workspaceId: number | null) => void;
}) {
  const approvalBusy = actingActionType === 'agent.approve';

  return (
    <View style={styles.page}>
      <SurfaceCard>
        <SurfaceHeader title="Session" subtitle="Resume the active Axon run and handle approvals without losing context." />
        {session ? (
          <View style={styles.stack}>
            <View style={styles.metrics}>
              <MetricCard label="Status" value={session.status || 'active'} accent="accent" />
              <MetricCard label="Workspace" value={session.workspace_id ?? 'None'} />
              <MetricCard label="Sessions" value={sessions?.length || 0} />
            </View>
            <View style={styles.pills}>
              {session.mode ? <StatusPill label={session.mode} tone="accent" /> : null}
              {session.agent_session_id ? <StatusPill label="Agent linked" tone="ok" /> : null}
              {approval ? <StatusPill label="Approval waiting" tone="warn" /> : null}
            </View>
            <Text style={styles.detail}>{session.summary || session.active_task || session.session_key}</Text>
            {onResume ? (
              <Pressable onPress={onResume} style={styles.resumeButton}>
                <Text style={styles.resumeButtonText}>Refresh this session</Text>
              </Pressable>
            ) : null}
            {onStop ? (
              <Pressable onPress={onStop} style={styles.stopButton}>
                <Text style={styles.stopButtonText}>Stop session</Text>
              </Pressable>
            ) : null}
          </View>
        ) : (
          <Text style={styles.empty}>No active Axon Online session yet.</Text>
        )}
      </SurfaceCard>
      <ExpoControlCard
        expo={expoProject}
        workspaceId={session?.workspace_id ?? null}
        busyActionType={expoBusyActionType}
        onExecuteAction={(actionType, payload) => {
          const workspaceId = typeof payload?.workspace_id === 'number' ? payload.workspace_id : session?.workspace_id ?? null;
          if (actionType === 'expo.project.status') {
            onExpoProjectStatus?.(workspaceId);
            return;
          }
          if (actionType === 'expo.build.android.dev') {
            onExpoBuildAndroidDev?.(workspaceId);
            return;
          }
          if (actionType === 'expo.build.ios.dev') {
            onExpoBuildIosDev?.(workspaceId);
            return;
          }
          if (actionType === 'expo.build.list') {
            onExpoBuildList?.(workspaceId);
            return;
          }
          if (actionType === 'expo.update.publish') {
            onExpoPublishUpdate?.(workspaceId);
          }
        }}
      />
      {approval ? (
        <SurfaceCard>
          <SurfaceHeader title="Approval needed" subtitle="Axon is paused on a protected step and can resume as soon as you approve the exact blocked action." />
          <Text style={styles.detail}>{approval.message || approval.resume_task || 'A protected action needs approval before Axon can continue.'}</Text>
          {approval.action_type ? (
            <Text style={styles.meta}>Action: {approval.action_type}</Text>
          ) : null}
          {approval.resume_task ? (
            <Text style={styles.meta}>After approval: {approval.resume_task}</Text>
          ) : null}
          {onApprovePending && approval.approval_action?.action_fingerprint ? (
            <Pressable onPress={onApprovePending} disabled={approvalBusy} style={[styles.approveButton, approvalBusy ? styles.approveButtonDisabled : null]}>
              <Text style={styles.approveButtonText}>{approvalBusy ? 'Approving…' : 'Approve once and resume'}</Text>
            </Pressable>
          ) : null}
        </SurfaceCard>
      ) : null}
      <ChallengeListCard
        challenges={challenges || []}
        actingActionType={actingActionType}
        onOpen={onOpenChallenge}
        onConfirm={onConfirmChallenge}
        onReject={onRejectChallenge}
      />
      <ReceiptListCard receipts={receipts || []} />
    </View>
  );
}

const styles = StyleSheet.create({
  page: {
    gap: 14,
  },
  stack: {
    gap: 10,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  detail: {
    color: '#e5eefb',
    fontSize: 13,
    lineHeight: 19,
  },
  meta: {
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 18,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
  resumeButton: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  resumeButtonText: {
    color: '#08111f',
    fontWeight: '800',
  },
  stopButton: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#742234',
    backgroundColor: '#2b141d',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  stopButtonText: {
    color: '#f8fafc',
    fontWeight: '700',
  },
  approveButton: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    backgroundColor: '#22c55e',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  approveButtonText: {
    color: '#08111f',
    fontWeight: '800',
  },
  approveButtonDisabled: {
    opacity: 0.65,
  },
});
