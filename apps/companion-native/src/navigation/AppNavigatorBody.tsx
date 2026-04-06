import React from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AttentionScreen } from '@/features/attention/AttentionScreen';
import { activeGateError, sessionGateCopy } from '@/features/auth/gateCopy';
import { CompanionOfflineGate } from '@/features/auth/CompanionOfflineGate';
import { CompanionSessionGate } from '@/features/auth/CompanionSessionGate';
import type { CompanionLinkState } from '@/features/auth/sessionState';
import { MissionControlScreen } from '@/features/mission/MissionControlDashboard';
import { ProjectsScreen } from '@/features/projects/ProjectsScreen';
import { SessionScreen } from '@/features/session/SessionScreen';
import { VoiceScreen } from '@/features/voice/VoiceCommandCenter';
import { SettingsTabScreen } from '@/navigation/SettingsTabScreen';
import type {
  AxonModeStatus,
  CompanionConfig,
  CompanionSession,
  ExpoProjectStatus,
  RiskChallenge,
  VaultProviderKeys,
  VaultStatus,
} from '@/types/companion';
import type { CompanionSettings } from '@/features/settings/useSettings';

type TabKey = 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings';

export function AppNavigatorBody({
  activeTab,
  config,
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
  onCopyAccessToken,
  onRePair,
  onSubmitCommand,
  onExecuteAction,
  onApprovePending,
  onConfirmChallenge,
  onRejectChallenge,
  onOpenChallenge,
  onToggleAutoNav,
  autoNavEnabled,
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
  authChecking,
  verifiedPairing,
  linkState,
  axon,
  axonError,
  onArmAxon,
  onDisarmAxon,
  onResumeSession,
  onStopSession,
}: {
  activeTab: TabKey;
  config: CompanionConfig;
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
  onCopyAccessToken?: () => void;
  onRePair?: () => void;
  onSubmitCommand: (text: string) => void;
  onExecuteAction: (actionType: string, payload?: Record<string, unknown>) => void;
  onApprovePending: () => void;
  onConfirmChallenge: (challenge: RiskChallenge) => void;
  onRejectChallenge: (challengeId: number) => void;
  onOpenChallenge: (challenge: RiskChallenge | null) => void;
  onToggleAutoNav?: () => void;
  autoNavEnabled?: boolean;
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
  authChecking?: boolean;
  verifiedPairing: boolean;
  linkState: CompanionLinkState;
  axon: { status: AxonModeStatus | null; busy: boolean };
  axonError?: string | null;
  onArmAxon: () => void;
  onDisarmAxon: () => void;
  onResumeSession?: () => void;
  onStopSession?: () => void;
}) {
  const insets = useSafeAreaInsets();
  const scrollPadding = {
    paddingTop: Math.max(20, insets.top + 12),
    paddingBottom: Math.max(24, insets.bottom + 32),
    paddingHorizontal: 16,
  };
  const wrapScrollable = (content: React.ReactNode) => (
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={[styles.scrollContent, scrollPadding]}
      keyboardShouldPersistTaps="handled"
    >
      {content}
    </ScrollView>
  );
  if (activeTab !== 'settings') {
    const gateCopy = sessionGateCopy(activeTab, linkState);
    const gateError = activeGateError(authError, bootstrapError);
    if (authChecking) {
      return wrapScrollable(
        <CompanionSessionGate
          title={gateCopy.title}
          subtitle={gateCopy.subtitle}
          detail={gateCopy.detail}
          busy
          apiBaseUrl={config.apiBaseUrl || ''}
          onChangeApiBaseUrl={onChangeApiBaseUrl}
          deviceName={deviceName}
          onChangeDeviceName={onChangeDeviceName}
          pairingPin={pairingPin}
          onChangePairingPin={onChangePairingPin}
          onPair={onPair}
          pairing={authPairing}
          error={gateError}
        />
      );
    }
    if (linkState === 'offline') {
      return wrapScrollable(
        <CompanionOfflineGate
          title={gateCopy.title}
          subtitle={gateCopy.subtitle}
          detail={gateCopy.detail}
          deviceName={deviceName}
          apiBaseUrl={config.apiBaseUrl || ''}
          error={gateError}
        />
      );
    }
    if (linkState !== 'linked' || !verifiedPairing) {
      return wrapScrollable(
        <CompanionSessionGate
          title={gateCopy.title}
          subtitle={gateCopy.subtitle}
          detail={gateCopy.detail}
          apiBaseUrl={config.apiBaseUrl || ''}
          onChangeApiBaseUrl={onChangeApiBaseUrl}
          deviceName={deviceName}
          onChangeDeviceName={onChangeDeviceName}
          pairingPin={pairingPin}
          onChangePairingPin={onChangePairingPin}
          onPair={onPair}
          pairing={authPairing}
          error={gateError}
        />
      );
    }
  }

  switch (activeTab) {
    case 'attention':
      return wrapScrollable(
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
          onSpeakText={speech.speak}
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
          onExitVoice={() => setActiveTab('mission')}
        />
      );
    case 'projects':
      return wrapScrollable(
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
      return wrapScrollable(
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
      return wrapScrollable(
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
          onCopyAccessToken={onCopyAccessToken}
          onRePair={onRePair}
          axonStatus={mission?.snapshot?.axon || null}
        />
      );
    case 'mission':
    default:
      return wrapScrollable(
        <MissionControlScreen
          snapshot={mission.snapshot}
          onOpenVoice={() => setActiveTab('voice')}
          onOpenAttention={() => setActiveTab('attention')}
          onOpenSessions={() => setActiveTab('sessions')}
          onOpenProjects={() => setActiveTab('projects')}
          onOpenSettings={() => setActiveTab('settings')}
          autoNavEnabled={autoNavEnabled}
          onToggleAutoNav={onToggleAutoNav}
        />
      );
  }
}

const styles = StyleSheet.create({
  scrollContent: {
    gap: 16,
  },
});
