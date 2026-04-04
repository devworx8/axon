import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { AxonModeCard } from '@/features/axon/AxonModeCard';
import { ExpoControlCard } from '@/features/expo/ExpoControlCard';
import { MissionHeroCard } from './MissionHeroCard';
import { QuickActionsCard } from './QuickActionsCard';
import { SystemStatusCard } from './SystemStatusCard';
import { VoiceCommandComposer } from '@/features/voice/VoiceCommandComposer';
import { VoiceOutcomeCard } from '@/features/voice/VoiceOutcomeCard';
import { ControlCapability, ExpoProjectStatus, PlatformSnapshot, TypedActionResult } from '@/types/companion';

export function MissionControlScreen({
  snapshot,
  digest,
  loading,
  sending,
  voiceMode,
  currentWorkspaceLabel,
  transcript,
  responseText,
  backend,
  tokensUsed,
  approval,
  capabilities,
  controlBusyActionType,
  lastAction,
  controlError,
  voiceError,
  speakingReply,
  expoProject,
  axonWakePhrase,
  onChangeAxonWakePhrase,
  axonBusy,
  axonError,
  onRefresh,
  onSubmitCommand,
  onExecuteAction,
  onApprovePending,
  onSpeakLatestReply,
  onStopSpeaking,
  onArmAxon,
  onDisarmAxon,
  onOpenVoice,
  onOpenAttention,
  onOpenProjects,
  onOpenSessions,
}: {
  snapshot: PlatformSnapshot | null;
  digest?: string;
  loading?: boolean;
  sending?: boolean;
  voiceMode?: string;
  currentWorkspaceLabel?: string;
  transcript?: string;
  responseText?: string;
  backend?: string;
  tokensUsed?: number;
  approval?: { message?: string; resume_task?: string } | null;
  capabilities?: ControlCapability[];
  controlBusyActionType?: string | null;
  lastAction?: TypedActionResult | null;
  controlError?: string | null;
  voiceError?: string | null;
  speakingReply?: boolean;
  expoProject?: ExpoProjectStatus | null;
  axonWakePhrase: string;
  onChangeAxonWakePhrase: (value: string) => void;
  axonBusy?: boolean;
  axonError?: string | null;
  onRefresh?: () => void;
  onSubmitCommand: (text: string) => void;
  onExecuteAction: (actionType: string) => void;
  onApprovePending: () => void;
  onSpeakLatestReply?: () => void;
  onStopSpeaking?: () => void;
  onArmAxon?: () => void;
  onDisarmAxon?: () => void;
  onOpenVoice: () => void;
  onOpenAttention: () => void;
  onOpenProjects: () => void;
  onOpenSessions: () => void;
}) {
  const projects = snapshot?.projects || [];
  const latestOutcomeSummary = lastAction?.receipt?.summary || snapshot?.latest_command_outcome?.summary;

  return (
    <View style={styles.stack}>
      <MissionHeroCard snapshot={snapshot} digest={digest} loading={loading} onRefresh={onRefresh} />
      <AxonModeCard
        axon={snapshot?.axon}
        wakePhrase={axonWakePhrase}
        onChangeWakePhrase={onChangeAxonWakePhrase}
        busy={axonBusy}
        error={axonError}
        onArm={onArmAxon}
        onDisarm={onDisarmAxon}
      />
      <QuickActionsCard
        quickActions={snapshot?.quick_actions}
        capabilities={capabilities}
        busyActionType={controlBusyActionType}
        onExecuteAction={onExecuteAction}
        onApprovePending={onApprovePending}
        onOpenVoice={onOpenVoice}
        onOpenProjects={onOpenProjects}
        onOpenAttention={onOpenAttention}
        onOpenSessions={onOpenSessions}
      />
      <SurfaceCard>
        <SurfaceHeader title="Command bus" subtitle="Type or tap once. Axon routes the request to the right workspace, approval, or typed action flow." />
        <VoiceCommandComposer
          onSubmit={onSubmitCommand}
          sending={sending}
          voiceMode={voiceMode}
          workspaceLabel={currentWorkspaceLabel}
          placeholder="Tell Axon what needs to happen across the platform."
          prompts={[
            'What needs attention right now?',
            'Inspect the focused workspace.',
            'Sync all connector signals.',
          ]}
        />
      </SurfaceCard>
      <VoiceOutcomeCard
        transcript={transcript}
        response={responseText || latestOutcomeSummary}
        backend={backend || (lastAction?.result ? 'action' : undefined)}
        tokensUsed={tokensUsed}
        approval={approval}
        error={voiceError || controlError}
        onOpenSession={onOpenSessions}
        speaking={speakingReply}
        onSpeak={onSpeakLatestReply}
        onStopSpeaking={onStopSpeaking}
      />
      <ExpoControlCard
        expo={expoProject}
        workspaceId={snapshot?.focus?.workspace_id ?? snapshot?.focus?.workspace?.id ?? null}
        capabilities={capabilities}
        busyActionType={controlBusyActionType}
        onExecuteAction={onExecuteAction}
      />
      <SystemStatusCard systems={snapshot?.systems} />
      <SurfaceCard>
        <SurfaceHeader title="MCP control plane" subtitle="Axon-managed servers and capability sessions stay visible from the mobile cockpit." />
        <Text style={styles.projectMeta}>
          {(snapshot?.mcp?.server_count || 0)} servers · {(snapshot?.mcp?.session_count || 0)} sessions
        </Text>
        <View style={styles.projectStack}>
          {(snapshot?.mcp?.servers || []).slice(0, 4).map((server) => (
            <View key={String(server.id)} style={styles.projectCard}>
              <Text style={styles.projectTitle}>{server.name}</Text>
              <Text style={styles.projectMeta}>
                {server.transport || 'adapter'} · {server.scope || 'global'} · {server.risk_tier || 'observe'}
              </Text>
            </View>
          ))}
        </View>
      </SurfaceCard>
      <SurfaceCard>
        <SurfaceHeader title="Projects at a glance" subtitle="Keep the most important workspaces and linked systems visible on the home surface." />
        <View style={styles.projectStack}>
          {projects.slice(0, 4).map((project) => (
            <Pressable
              key={String(project.workspace?.id || project.workspace?.name || Math.random())}
              onPress={onOpenProjects}
              style={styles.projectCard}
            >
              <Text style={styles.projectTitle}>{project.workspace?.name || 'Workspace'}</Text>
              <Text style={styles.projectPath}>{project.workspace?.path || 'No path recorded'}</Text>
              <Text style={styles.projectMeta}>
                {(project.relationships || []).length} linked systems · {project.attention?.counts?.now || 0} urgent
              </Text>
              {project.preview?.status ? (
                <Text style={styles.projectMeta}>
                  Preview {String(project.preview.status).replace('_', ' ')}
                  {project.preview?.url ? ` · ${String(project.preview.url)}` : ''}
                </Text>
              ) : null}
            </Pressable>
          ))}
        </View>
      </SurfaceCard>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 14,
  },
  projectStack: {
    gap: 10,
  },
  projectCard: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 4,
    backgroundColor: '#0b1627',
  },
  projectTitle: {
    color: '#e5eefb',
    fontSize: 14,
    fontWeight: '800',
  },
  projectPath: {
    color: '#7f93ad',
    fontSize: 12,
    lineHeight: 18,
  },
  projectMeta: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '600',
  },
});
