import React from 'react';
import { Text } from 'react-native';
import { SurfaceCard } from '@/components/SurfaceCard';
import { AttentionScreen } from '@/features/attention/AttentionScreen';
import { AuthScreen } from '@/features/auth/AuthScreen';
import { MissionControlScreen } from '@/features/mission/MissionControlScreen';
import { ProjectsScreen } from '@/features/projects/ProjectsScreen';
import { SessionScreen } from '@/features/session/SessionScreen';
import { VoiceScreen } from '@/features/voice/VoiceScreen';
import { SettingsTabScreen } from '@/navigation/SettingsTabScreen';
import type {
  AxonModeStatus,
  CompanionConfig,
  CompanionSession,
  ExpoProjectStatus,
  RiskChallenge,
  TypedActionResult,
  VaultProviderKeys,
  VaultStatus,
} from '@/types/companion';
import type { CompanionSettings } from '@/features/settings/useSettings';

type TabKey = 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings';

const EMPTY_INBOX = {
  now: [],
  waiting_on_me: [],
  watch: [],
};

export function AppNavigatorBody({
  activeTab,
  config,
  colors,
  authError,
  authPairing,
  bootstrapError,
  deviceName,
  pairingPin,
  onChangeApiBaseUrl,
  onChangeDeviceName,
  onChangePairingPin,
  onPair,
  mission,
  control,
  voice,
  speech,
  settings,
  liveVoice,
  currentWorkspaceId,
  currentWorkspaceLabel,
  currentSessionId,
  activeSession,
  attentionSummary,
  attentionInbox,
  expoProject,
  vaultStatus,
  vaultProviderKeys,
  vaultBusy,
  vaultError,
  vaultMasterPassword,
  vaultTotpCode,
  vaultRememberMe,
  onChangeVaultMasterPassword,
  onChangeVaultTotpCode,
  onChangeVaultRememberMe,
  onRefreshVault,
  onUnlockVault,
  onUnlockVaultWithBiometrics,
  onLockVault,
  onSubmitCommand,
  onExecuteAction,
  onApprovePending,
  onConfirmChallenge,
  onRejectChallenge,
  onOpenChallenge,
  onFocusWorkspace,
  onInspectWorkspace,
  onRestartPreview,
  onStopPreview,
  onDeploy,
  onRollback,
  onExpoProjectStatus,
  onExpoBuildAndroidDev,
  onExpoBuildIosDev,
  onExpoBuildList,
  onExpoPublishUpdate,
  onRefreshMission,
  setActiveTab,
  verifiedPairing,
  axon,
  axonError,
  onArmAxon,
  onDisarmAxon,
  onResumeSession,
  onStopSession,
}: {
  activeTab: TabKey;
  config: CompanionConfig;
  colors: Record<string, string>;
  authError?: string | null;
  authPairing?: boolean;
  bootstrapError?: string | null;
  deviceName: string;
  pairingPin: string;
  onChangeApiBaseUrl: (value: string) => void;
  onChangeDeviceName: (value: string) => void;
  onChangePairingPin: (value: string) => void;
  onPair: () => void;
  mission: Record<string, any>;
  control: Record<string, any>;
  voice: Record<string, any>;
  speech: Record<string, any>;
  settings: { settings: CompanionSettings; setSettings: React.Dispatch<React.SetStateAction<CompanionSettings>>; setApiBaseUrl: (value: string) => void };
  liveVoice: Record<string, any>;
  currentWorkspaceId: number | null;
  currentWorkspaceLabel?: string;
  currentSessionId: number | null;
  activeSession: CompanionSession | null;
  attentionSummary: Record<string, any>;
  attentionInbox: Record<string, any>;
  expoProject: ExpoProjectStatus | null;
  vaultStatus: VaultStatus | null;
  vaultProviderKeys: VaultProviderKeys | null;
  vaultBusy: boolean;
  vaultError: string | null;
  vaultMasterPassword: string;
  vaultTotpCode: string;
  vaultRememberMe: boolean;
  onChangeVaultMasterPassword: (value: string) => void;
  onChangeVaultTotpCode: (value: string) => void;
  onChangeVaultRememberMe: (value: boolean) => void;
  onRefreshVault: () => void;
  onUnlockVault: () => void;
  onUnlockVaultWithBiometrics: () => void;
  onLockVault: () => void;
  onSubmitCommand: (text: string) => void;
  onExecuteAction: (actionType: string, payload?: Record<string, unknown>) => void;
  onApprovePending: () => void;
  onConfirmChallenge: (challenge: RiskChallenge) => void;
  onRejectChallenge: (challengeId: number) => void;
  onOpenChallenge: (challenge: RiskChallenge | null) => void;
  onFocusWorkspace: (workspaceId: number | null) => void;
  onInspectWorkspace: (workspaceId: number | null) => void;
  onRestartPreview: (workspaceId: number | null) => void;
  onStopPreview: (workspaceId: number | null) => void;
  onDeploy: (workspaceId: number | null) => void;
  onRollback: (workspaceId: number | null) => void;
  onExpoProjectStatus: (workspaceId: number | null) => void;
  onExpoBuildAndroidDev: (workspaceId: number | null) => void;
  onExpoBuildIosDev: (workspaceId: number | null) => void;
  onExpoBuildList: (workspaceId: number | null) => void;
  onExpoPublishUpdate: (workspaceId: number | null) => void;
  onRefreshMission: () => void;
  setActiveTab: (tab: TabKey) => void;
  verifiedPairing: boolean;
  axon: { status: AxonModeStatus | null; busy: boolean };
  axonError?: string | null;
  onArmAxon: () => void;
  onDisarmAxon: () => void;
  onResumeSession?: () => void;
  onStopSession?: () => void;
}) {
  switch (activeTab) {
    case 'attention':
      return (
        <AttentionScreen
          summary={{ counts: attentionSummary.counts || {} }}
          inbox={{
            now: attentionInbox.now || [],
            waiting_on_me: attentionInbox.waiting_on_me || [],
            watch: attentionInbox.watch || [],
          }}
          onResolve={(id) => onExecuteAction('attention.resolve', { attention_id: id })}
          onSync={() => onExecuteAction('attention.sync', { workspace_id: currentWorkspaceId ?? undefined })}
          syncing={control.actingActionType === 'attention.sync'}
        />
      );
    case 'voice':
      return (
        <VoiceScreen
          onSubmit={onSubmitCommand}
          sending={voice.sending}
          transcript={voice.lastTranscript}
          response={voice.responseText}
          backend={voice.lastResult?.backend}
          tokensUsed={voice.lastResult?.tokens_used}
          approval={voice.lastResult?.approval_required}
          voiceMode={settings.settings.alwaysListening ? 'live' : 'push_to_talk'}
          error={voice.error || control.error}
          workspaceLabel={currentWorkspaceLabel}
          onOpenSession={() => setActiveTab('sessions')}
          speaking={speech.speaking}
          onSpeak={voice.responseText ? () => speech.speak(voice.responseText) : undefined}
          onStopSpeaking={speech.stop}
          liveVoiceStatus={liveVoice.voiceStatus}
          checkingVoiceStatus={liveVoice.checkingStatus}
          recording={liveVoice.isRecording}
          transcribing={liveVoice.transcribing}
          recordingDuration={liveVoice.durationLabel}
          liveTranscript={liveVoice.lastTranscript}
          liveEngine={liveVoice.lastEngine}
          liveError={liveVoice.error}
          onStartLiveVoice={() => liveVoice.startRecording().catch(() => undefined)}
          onStopLiveVoice={() => liveVoice.stopAndSubmit().catch(() => undefined)}
          onRefreshLiveVoice={() => liveVoice.refreshVoiceStatus().catch(() => undefined)}
          axon={axon.status}
          axonWakePhrase={settings.settings.axonWakePhrase}
          onChangeAxonWakePhrase={(value) => settings.setSettings(current => ({ ...current, axonWakePhrase: value }))}
          axonBusy={axon.busy}
          axonError={axonError}
          onArmAxon={() => onArmAxon()}
          onDisarmAxon={() => onDisarmAxon()}
        />
      );
    case 'projects':
      return (
        <ProjectsScreen
          projects={mission.snapshot?.projects || []}
          activeWorkspaceId={currentWorkspaceId}
          expoProject={expoProject}
          expoBusyActionType={control.actingActionType}
          onFocusWorkspace={(workspaceId) => onFocusWorkspace(workspaceId)}
          onInspectWorkspace={(workspaceId) => onInspectWorkspace(workspaceId)}
          onRestartPreview={(workspaceId) => onRestartPreview(workspaceId)}
          onStopPreview={(workspaceId) => onStopPreview(workspaceId)}
          onDeploy={(workspaceId) => onDeploy(workspaceId)}
          onRollback={(workspaceId) => onRollback(workspaceId)}
          onExpoProjectStatus={(workspaceId) => onExpoProjectStatus(workspaceId)}
          onExpoBuildAndroidDev={(workspaceId) => onExpoBuildAndroidDev(workspaceId)}
          onExpoBuildIosDev={(workspaceId) => onExpoBuildIosDev(workspaceId)}
          onExpoBuildList={(workspaceId) => onExpoBuildList(workspaceId)}
          onExpoPublishUpdate={(workspaceId) => onExpoPublishUpdate(workspaceId)}
        />
      );
    case 'sessions':
      return (
        <SessionScreen
          sessions={mission.snapshot?.sessions || []}
          session={activeSession}
          expoProject={expoProject}
          expoBusyActionType={control.actingActionType}
          onExpoProjectStatus={(workspaceId) => onExpoProjectStatus(workspaceId)}
          onExpoBuildAndroidDev={(workspaceId) => onExpoBuildAndroidDev(workspaceId)}
          onExpoBuildIosDev={(workspaceId) => onExpoBuildIosDev(workspaceId)}
          onExpoBuildList={(workspaceId) => onExpoBuildList(workspaceId)}
          onExpoPublishUpdate={(workspaceId) => onExpoPublishUpdate(workspaceId)}
          approval={voice.lastResult?.approval_required}
          challenges={control.challenges}
          receipts={control.receipts}
          actingActionType={control.actingActionType}
          onOpenChallenge={onOpenChallenge}
          onResume={activeSession ? onResumeSession : undefined}
          onStop={activeSession ? onStopSession : undefined}
          onConfirmChallenge={onConfirmChallenge}
          onRejectChallenge={onRejectChallenge}
          onApprovePending={voice.lastResult?.approval_required?.approval_action ? onApprovePending : undefined}
        />
      );
    case 'settings':
      return (
        <SettingsTabScreen
          settings={settings}
          config={config}
          vaultStatus={vaultStatus}
          vaultProviderKeys={vaultProviderKeys}
          vaultBusy={vaultBusy}
          vaultError={vaultError}
          vaultMasterPassword={vaultMasterPassword}
          vaultTotpCode={vaultTotpCode}
          vaultRememberMe={vaultRememberMe}
          onChangeVaultMasterPassword={onChangeVaultMasterPassword}
          onChangeVaultTotpCode={onChangeVaultTotpCode}
          onChangeVaultRememberMe={onChangeVaultRememberMe}
          onRefreshVault={onRefreshVault}
          onUnlockVault={onUnlockVault}
          onUnlockVaultWithBiometrics={onUnlockVaultWithBiometrics}
          onLockVault={onLockVault}
        />
      );
    case 'mission':
    default:
      if (!config.accessToken) {
        return (
          <>
            <SurfaceCard>
              <Text style={{ fontSize: 11, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 1.1, color: colors.accent }}>Axon Online</Text>
              <Text style={{ fontSize: 24, fontWeight: '800', color: colors.text }}>Pair your mobile operator</Text>
              <Text style={{ marginTop: 8, fontSize: 14, lineHeight: 20, color: colors.muted }}>Link this device to live Axon first, then your phone can act like a real command center.</Text>
            </SurfaceCard>
            <AuthScreen
              apiBaseUrl={config.apiBaseUrl || ''}
              onChangeApiBaseUrl={onChangeApiBaseUrl}
              deviceName={deviceName}
              onChangeDeviceName={onChangeDeviceName}
              pairingPin={pairingPin}
              onChangePairingPin={onChangePairingPin}
              onPair={onPair}
              pairing={authPairing}
              error={authError || bootstrapError}
            />
          </>
        );
      }
      return (
        <MissionControlScreen
          snapshot={mission.snapshot}
          digest={mission.digest}
          loading={mission.loading || control.refreshing}
          sending={voice.sending}
          voiceMode={settings.settings.alwaysListening ? 'live' : 'push_to_talk'}
          currentWorkspaceLabel={currentWorkspaceLabel}
          transcript={voice.lastTranscript}
          responseText={voice.responseText}
          backend={voice.lastResult?.backend}
          tokensUsed={voice.lastResult?.tokens_used}
          approval={voice.lastResult?.approval_required}
          capabilities={control.capabilities}
          controlBusyActionType={control.actingActionType}
          lastAction={control.lastAction as TypedActionResult | null}
          controlError={control.error || mission.error}
          voiceError={voice.error || bootstrapError}
          speakingReply={speech.speaking}
          onRefresh={onRefreshMission}
          onSubmitCommand={onSubmitCommand}
          onApprovePending={onApprovePending}
          onExecuteAction={(actionType) => {
            if (actionType === 'agent.approve') {
              onApprovePending();
              return;
            }
            onExecuteAction(actionType);
          }}
          onSpeakLatestReply={voice.responseText ? () => speech.speak(voice.responseText) : undefined}
          onStopSpeaking={speech.stop}
          onOpenVoice={() => setActiveTab('voice')}
          onOpenAttention={() => setActiveTab('attention')}
          onOpenProjects={() => setActiveTab('projects')}
          onOpenSessions={() => setActiveTab('sessions')}
          expoProject={expoProject}
          axonWakePhrase={settings.settings.axonWakePhrase}
          onChangeAxonWakePhrase={(value) => settings.setSettings(current => ({ ...current, axonWakePhrase: value }))}
          axonBusy={axon.busy}
          axonError={axonError}
          onArmAxon={onArmAxon}
          onDisarmAxon={onDisarmAxon}
        />
      );
  }
}
