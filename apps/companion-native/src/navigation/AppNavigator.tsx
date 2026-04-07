import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Clipboard, KeyboardAvoidingView, Platform, StyleSheet, View } from 'react-native';

import { BottomTabBar } from '@/components/BottomTabBar';
import {
  shouldShowCompanionTabBar,
} from '@/features/auth/linkPresentation';
import {
  fetchMobileVaultProviderKeys,
  fetchMobileVaultStatus,
  lockMobileVault,
  unlockMobileVault,
  unlockMobileVaultWithBiometric,
} from '@/api/vault';
import { useAxonMobileRuntime } from '@/features/axon/useAxonMobileRuntime';
import { useCompanionBootstrap } from '@/features/auth/useCompanionBootstrap';
import { useStoredCompanionConfig } from '@/features/auth/useStoredCompanionConfig';
import { useAuth } from '@/features/auth/useAuth';
import { useMobileControl } from '@/features/control/useMobileControl';
import { useMissionControl } from '@/features/mission/useMissionControl';
import { usePresence } from '@/features/presence/usePresence';
import { clearCompanionSession, hasStoredCompanionPairing } from '@/features/auth/sessionState';
import { RiskChallengeSheet } from '@/features/session/RiskChallengeSheet';
import { useSettings } from '@/features/settings/useSettings';
import { useVoice } from '@/features/voice/useVoice';
import { verifyLocalBiometric } from '@/lib/localBiometric';
import { AppNavigatorBody } from '@/navigation/AppNavigatorBody';
import { useWorkspaceActionHandlers } from '@/navigation/useWorkspaceActionHandlers';
import { useTheme } from '@/theme/ThemeProvider';
import { CompanionConfig, RiskChallenge, TypedActionRequest, VaultProviderKeys, VaultStatus } from '@/types/companion';

type TabKey = 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings';

const EMPTY_ATTENTION = {
  counts: { now: 0, waiting_on_me: 0, watch: 0 },
  top_now: [],
  top_waiting_on_me: [],
  top_watch: [],
};

const EMPTY_INBOX = {
  now: [],
  waiting_on_me: [],
  watch: [],
  counts: { now: 0, waiting_on_me: 0, watch: 0 },
};

export function AppNavigator() {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState<TabKey>('voice');
  const [autoNavEnabled, setAutoNavEnabled] = useState(true);
  const [config, setConfig] = useState<CompanionConfig>({ apiBaseUrl: '', workspaceId: null, sessionId: null, deviceId: null });
  const [deviceName, setDeviceName] = useState('Axon phone');
  const [pairingPin, setPairingPin] = useState('');
  const [selectedChallenge, setSelectedChallenge] = useState<RiskChallenge | null>(null);
  const [vaultStatus, setVaultStatus] = useState<VaultStatus | null>(null);
  const [vaultProviderKeys, setVaultProviderKeys] = useState<VaultProviderKeys | null>(null);
  const [vaultBusy, setVaultBusy] = useState(false);
  const [vaultError, setVaultError] = useState<string | null>(null);
  const [vaultMasterPassword, setVaultMasterPassword] = useState('');
  const [vaultTotpCode, setVaultTotpCode] = useState('');
  const [vaultRememberMe, setVaultRememberMe] = useState(true);

  const auth = useAuth(config, setConfig);
  const settings = useSettings(config, setConfig);
  const presence = usePresence(config);
  const mission = useMissionControl(config);
  const control = useMobileControl(config);
  const lastAutoNavRef = useRef(0);
  const voice = useVoice(config, (nextSession) => {
    setConfig((current) => ({
      ...current,
      sessionId: nextSession.id,
      workspaceId: nextSession.workspace_id ?? current.workspaceId ?? null,
    }));
  });

  useStoredCompanionConfig(config, setConfig, setDeviceName);
  const { bootstrapError, verifiedPairing, verifyingPairing, linkState } = useCompanionBootstrap({
    config,
    setConfig,
    setDeviceName,
    restoreSession: auth.restoreSession,
    refreshMission: mission.refresh,
    refreshControl: control.refresh,
    setPresence: presence.setPresence,
    setVaultStatus,
    setVaultProviderKeys,
  });

  useEffect(() => {
    const focusWorkspace = mission.snapshot?.focus?.workspace?.id ?? config.workspaceId ?? null;
    const focusSession = mission.snapshot?.sessions?.[0]?.id ?? config.sessionId ?? null;
    if (focusWorkspace === config.workspaceId && focusSession === config.sessionId) {
      return;
    }
    if (!focusWorkspace && !focusSession) {
      return;
    }
    setConfig((current) => ({
      ...current,
      workspaceId: focusWorkspace ?? current.workspaceId ?? null,
      sessionId: focusSession ?? current.sessionId ?? null,
    }));
  }, [config.sessionId, config.workspaceId, mission.snapshot?.focus?.workspace?.id, mission.snapshot?.sessions?.[0]?.id]);

  const missionRefreshRef = useRef(mission.refresh);
  const controlRefreshRef = useRef(control.refresh);
  useEffect(() => {
    missionRefreshRef.current = mission.refresh;
  }, [mission.refresh]);
  useEffect(() => {
    controlRefreshRef.current = control.refresh;
  }, [control.refresh]);

  useEffect(() => {
    if (!config.accessToken) return;
    const timer = setInterval(() => {
      missionRefreshRef.current(undefined, undefined, { silent: true }).catch(() => undefined);
      controlRefreshRef.current().catch(() => undefined);
      fetchMobileVaultStatus(config).then(setVaultStatus).catch(() => undefined);
      fetchMobileVaultProviderKeys(config).then(setVaultProviderKeys).catch(() => undefined);
    }, 15000);
    return () => clearInterval(timer);
  }, [config.accessToken, config.apiBaseUrl]);

  const activeSession = mission.snapshot?.sessions?.[0] || null;
  const currentWorkspaceLabel = mission.snapshot?.focus?.workspace?.name || undefined;
  const attentionSummary = mission.snapshot?.attention?.summary || EMPTY_ATTENTION;
  const attentionInbox = mission.snapshot?.attention?.inbox || EMPTY_INBOX;
  const currentWorkspaceId = config.workspaceId ?? mission.snapshot?.focus?.workspace?.id ?? null;
  const currentSessionId = config.sessionId ?? activeSession?.id ?? null;
  const hasStoredPairing = hasStoredCompanionPairing(config);
  const focusedProject = useMemo(() => {
    const projects = mission.snapshot?.projects || [];
    if (currentWorkspaceId !== null) {
      const match = projects.find((project) => project.workspace?.id === currentWorkspaceId);
      if (match) {
        return match;
      }
    }
    return projects[0] || null;
  }, [currentWorkspaceId, mission.snapshot?.projects]);
  const expoProject = focusedProject?.expo || null;
  const autoNavTarget = useMemo(() => {
    if (!verifiedPairing || !config.accessToken) return null;
    if ((control.challenges?.length || 0) > 0 || voice.lastResult?.approval_required) {
      return 'sessions' as TabKey;
    }
    if (Number(attentionSummary.counts?.now || 0) > 0) {
      return 'attention' as TabKey;
    }
    return null;
  }, [attentionSummary.counts?.now, config.accessToken, control.challenges, verifiedPairing, voice.lastResult?.approval_required]);

  useEffect(() => {
    if (!autoNavEnabled) return;
    if (activeTab !== 'mission') return;
    if (!autoNavTarget) return;
    const now = Date.now();
    if (now - lastAutoNavRef.current < 6000) return;
    lastAutoNavRef.current = now;
    setActiveTab(autoNavTarget);
  }, [activeTab, autoNavEnabled, autoNavTarget]);

  const syncMission = React.useCallback(async () => {
    await Promise.allSettled([
      mission.refresh(currentWorkspaceId, currentSessionId),
      control.refresh(),
      fetchMobileVaultStatus(config).then(setVaultStatus),
      fetchMobileVaultProviderKeys(config).then(setVaultProviderKeys),
    ]);
  }, [config, control.refresh, currentSessionId, currentWorkspaceId, mission.refresh]);

  const axonRuntime = useAxonMobileRuntime({
    config,
    settings: settings.settings,
    missionAxonSnapshot: mission.snapshot?.axon || null,
    voice,
    syncMission,
    setActiveTab,
    activeTab,
  });
  const { speech, liveVoice, axonMode, handleVoiceSubmit, handleArmAxon, handleDisarmAxon } = axonRuntime;

  useEffect(() => {
    const message = String(
      voice.responseText
        || voice.lastResult?.approval_required?.message
        || voice.lastResult?.approval_required?.resume_task
        || '',
    ).trim();
    if (message) {
      speech.autoSpeak(message);
    }
  }, [
    speech.autoSpeak,
    voice.lastResult?.approval_required?.message,
    voice.lastResult?.approval_required?.resume_task,
    voice.responseText,
  ]);

  useEffect(() => {
    const message = String(
      control.lastAction?.challenge?.summary
        || control.lastAction?.receipt?.summary
        || '',
    ).trim();
    if (message) {
      speech.autoSpeak(message);
    }
  }, [control.lastAction?.challenge?.summary, control.lastAction?.receipt?.summary, speech.autoSpeak]);

  const refreshVault = React.useCallback(async () => {
    if (!config.accessToken) return;
    setVaultError(null);
    const [status, providerKeys] = await Promise.all([
      fetchMobileVaultStatus(config),
      fetchMobileVaultProviderKeys(config),
    ]);
    setVaultStatus(status);
    setVaultProviderKeys(providerKeys);
  }, [config]);

  const handleUnlockVault = React.useCallback(async () => {
    if (!config.accessToken) return;
    setVaultBusy(true);
    setVaultError(null);
    try {
      await unlockMobileVault(
        {
          master_password: vaultMasterPassword,
          totp_code: vaultTotpCode,
          remember_me: vaultRememberMe,
        },
        config,
      );
      setVaultMasterPassword('');
      setVaultTotpCode('');
      await refreshVault();
      await syncMission();
    } catch (error) {
      setVaultError(error instanceof Error ? error.message : 'Vault unlock failed');
    } finally {
      setVaultBusy(false);
    }
  }, [config, refreshVault, syncMission, vaultMasterPassword, vaultRememberMe, vaultTotpCode]);

  const handleUnlockVaultWithBiometrics = React.useCallback(async () => {
    if (!config.accessToken) return;
    if (!vaultMasterPassword.trim()) {
      setVaultError('Enter the vault master password to use biometric re-unlock.');
      return;
    }
    setVaultBusy(true);
    setVaultError(null);
    try {
      const verifiedVia = await verifyLocalBiometric('Unlock Axon vault with biometrics');
      if (verifiedVia !== 'biometric_local') {
        throw new Error('Biometric hardware is required for this unlock fallback.');
      }
      await unlockMobileVaultWithBiometric(
        {
          master_password: vaultMasterPassword,
          remember_me: vaultRememberMe,
          verified_via: verifiedVia,
        },
        config,
      );
      setVaultMasterPassword('');
      setVaultTotpCode('');
      await refreshVault();
      await syncMission();
    } catch (error) {
      setVaultError(error instanceof Error ? error.message : 'Biometric vault unlock failed');
    } finally {
      setVaultBusy(false);
    }
  }, [config, refreshVault, syncMission, vaultMasterPassword, vaultRememberMe]);

  const handleLockVault = React.useCallback(async () => {
    if (!config.accessToken) return;
    setVaultBusy(true);
    setVaultError(null);
    try {
      await lockMobileVault(config);
      await refreshVault();
      await syncMission();
    } catch (error) {
      setVaultError(error instanceof Error ? error.message : 'Vault lock failed');
    } finally {
      setVaultBusy(false);
    }
  }, [config, refreshVault, syncMission]);

  const handleRePair = React.useCallback(() => {
    setConfig((current) => ({
      ...clearCompanionSession(current),
      deviceId: null,
      deviceKey: '',
      restoreToken: '',
      sessionId: null,
      workspaceId: null,
    }));
    setPairingPin('');
    setActiveTab('mission');
  }, []);

  useEffect(() => {
    if (!config.accessToken) return;
    const voiceState = axonMode.status?.armed
      ? (axonMode.status.monitoring_state === 'degraded'
          ? 'axon_degraded'
          : axonMode.status.monitoring_state === 'engaged'
            ? 'axon_engaged'
            : 'axon_armed')
      : (settings.settings.alwaysListening ? 'live' : 'push_to_talk');
    presence.heartbeat(
      config.workspaceId ?? null,
      config.sessionId ?? null,
      voiceState,
      activeTab === 'mission' ? '/' : `/${activeTab}`,
    ).catch(() => undefined);
  }, [
    activeTab,
    axonMode.status?.armed,
    axonMode.status?.monitoring_state,
    config.accessToken,
    config.workspaceId,
    config.sessionId,
    presence.heartbeat,
    settings.settings.alwaysListening,
  ]);

  const handleExecuteAction = React.useCallback(async (actionType: string, payload?: Record<string, unknown>) => {
    const request: TypedActionRequest = {
      action_type: actionType,
      session_id: currentSessionId,
      workspace_id: currentWorkspaceId,
      payload: payload || {},
    };
    const result = await control.executeAction(request);
    if (actionType === 'session.stop') {
      setConfig((current) => ({ ...current, sessionId: null }));
    }
    if (result.challenge) {
      setSelectedChallenge(result.challenge);
      setActiveTab('sessions');
    }
    await syncMission();
    return result;
  }, [control.executeAction, currentSessionId, currentWorkspaceId, syncMission]);

  const handleApprovePending = React.useCallback(async () => {
    const approval = voice.lastResult?.approval_required;
    const approvalAction = approval?.approval_action;
    if (!approval || !approvalAction) {
      setActiveTab('sessions');
      return;
    }
    await handleExecuteAction('agent.approve', {
      approval_action: approvalAction,
      scope: 'once',
      agent_session_id: approvalAction.session_id,
    });
  }, [handleExecuteAction, voice.lastResult?.approval_required]);

  const workspaceActions = useWorkspaceActionHandlers({
    setConfig,
    setActiveTab,
    setPreferredWorkspaceId: settings.setPreferredWorkspaceId,
    executeAction: handleExecuteAction,
    refreshMission: mission.refresh,
    currentSessionId,
  });

  const handleConfirmChallenge = React.useCallback(async (challenge: RiskChallenge) => {
    await control.confirmChallenge(challenge);
    setSelectedChallenge(null);
    await syncMission();
  }, [control.confirmChallenge, syncMission]);

  const handleRejectChallenge = React.useCallback(async (challengeId: number) => {
    await control.rejectChallenge(challengeId);
    setSelectedChallenge((current) => (current?.id === challengeId ? null : current));
    await syncMission();
  }, [control.rejectChallenge, syncMission]);

  useEffect(() => {
    if (selectedChallenge && !control.challenges.some((item) => item.id === selectedChallenge.id)) {
      setSelectedChallenge(null);
    }
  }, [control.challenges, selectedChallenge]);

  useEffect(() => {
    if (!selectedChallenge && control.lastAction?.challenge) {
      setSelectedChallenge(control.lastAction.challenge);
    }
  }, [control.lastAction?.challenge, selectedChallenge]);

  const tabs = useMemo(() => ([
    ['mission', 'Mission Control', 'Primary cockpit status and commands.'],
    ['voice', 'Voice', 'Capture and route voice commands.'],
    ['attention', 'Attention', 'Triage now, waiting, and watch.'],
    ['projects', 'Projects', 'Workspace focus and linked systems.'],
    ['sessions', 'Sessions', 'Approvals, challenges, and active runs.'],
    ['settings', 'Settings', 'Device, vault, and voice tuning.'],
  ] as const), []);
  const body = (
    <AppNavigatorBody
      activeTab={activeTab}
      config={config}
      authError={auth.error}
      authPairing={auth.pairing}
      bootstrapError={bootstrapError}
      deviceName={deviceName}
      pairingPin={pairingPin}
      onChangeApiBaseUrl={(value) => setConfig((current) => ({ ...current, apiBaseUrl: value }))}
      onChangeDeviceName={setDeviceName}
      onChangePairingPin={setPairingPin}
      onPair={() => auth.pair(deviceName, pairingPin).catch(() => undefined)}
      mission={mission}
      control={control}
      voice={voice}
      speech={speech}
      settings={settings}
      liveVoice={liveVoice}
      currentWorkspaceId={currentWorkspaceId}
      currentWorkspaceLabel={currentWorkspaceLabel}
      currentSessionId={currentSessionId}
      activeSession={activeSession}
      attentionSummary={attentionSummary}
      attentionInbox={attentionInbox}
      expoProject={expoProject}
      vaultStatus={vaultStatus}
      vaultProviderKeys={vaultProviderKeys}
      vaultBusy={vaultBusy}
      vaultError={vaultError}
      vaultMasterPassword={vaultMasterPassword}
      vaultTotpCode={vaultTotpCode}
      vaultRememberMe={vaultRememberMe}
      onChangeVaultMasterPassword={setVaultMasterPassword}
      onChangeVaultTotpCode={setVaultTotpCode}
      onChangeVaultRememberMe={setVaultRememberMe}
      onRefreshVault={() => refreshVault().catch(() => undefined)}
      onUnlockVault={() => handleUnlockVault().catch(() => undefined)}
      onUnlockVaultWithBiometrics={() => handleUnlockVaultWithBiometrics().catch(() => undefined)}
      onLockVault={() => handleLockVault().catch(() => undefined)}
      onCopyAccessToken={
        __DEV__
          ? () => {
            const token = config.accessToken || config.tokenPair?.access_token || '';
            if (token) {
              Clipboard.setString(token);
            }
          }
          : undefined
      }
      onRePair={handleRePair}
      onSubmitCommand={handleVoiceSubmit}
      onExecuteAction={(actionType, payload) => handleExecuteAction(actionType, payload).catch(() => undefined)}
      onApprovePending={() => handleApprovePending().catch(() => undefined)}
      onConfirmChallenge={(challenge) => handleConfirmChallenge(challenge).catch(() => undefined)}
      onRejectChallenge={(challengeId) => handleRejectChallenge(challengeId).catch(() => undefined)}
      onOpenChallenge={setSelectedChallenge}
      autoNavEnabled={autoNavEnabled}
      onToggleAutoNav={() => setAutoNavEnabled((current) => !current)}
      onFocusWorkspace={(workspaceId) => workspaceActions.focusWorkspace(workspaceId).catch(() => undefined)}
      onInspectWorkspace={(workspaceId) => workspaceActions.inspectWorkspace(workspaceId).catch(() => undefined)}
      onRestartPreview={(workspaceId) => workspaceActions.restartPreview(workspaceId).catch(() => undefined)}
      onStopPreview={(workspaceId) => workspaceActions.stopPreview(workspaceId).catch(() => undefined)}
      onDeploy={(workspaceId) => workspaceActions.deployWorkspace(workspaceId).catch(() => undefined)}
      onRollback={(workspaceId) => workspaceActions.rollbackWorkspace(workspaceId).catch(() => undefined)}
      onExpoProjectStatus={(workspaceId) => workspaceActions.expoProjectStatus(workspaceId).catch(() => undefined)}
      onExpoBuildAndroidDev={(workspaceId) => workspaceActions.expoBuildAndroidDev(workspaceId).catch(() => undefined)}
      onExpoBuildIosDev={(workspaceId) => workspaceActions.expoBuildIosDev(workspaceId).catch(() => undefined)}
      onExpoBuildList={(workspaceId) => workspaceActions.expoBuildList(workspaceId).catch(() => undefined)}
      onExpoPublishUpdate={(workspaceId) => workspaceActions.expoPublishUpdate(workspaceId).catch(() => undefined)}
      onRefreshMission={() => syncMission().catch(() => undefined)}
      setActiveTab={setActiveTab}
      authChecking={verifyingPairing && linkState === 'checking'}
      verifiedPairing={verifiedPairing}
      linkState={linkState}
      axon={{ status: axonMode.status, busy: axonMode.busy }}
      axonError={axonMode.error}
      onArmAxon={() => handleArmAxon().catch(() => undefined)}
      onDisarmAxon={() => handleDisarmAxon().catch(() => undefined)}
      onResumeSession={activeSession ? () => handleExecuteAction('session.resume', { session_key: activeSession.session_key, agent_session_id: activeSession.agent_session_id }).catch(() => undefined) : undefined}
      onStopSession={activeSession ? () => handleExecuteAction('session.stop').catch(() => undefined) : undefined}
    />
  );

  const urgentCount = Number(attentionSummary.counts?.now || 0);
  const showTabBar = shouldShowCompanionTabBar(linkState, hasStoredPairing) && activeTab !== 'voice';

  return (
    <KeyboardAvoidingView
      style={styles.shell}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 64 : 0}
    >
      <View style={styles.main}>
        <View style={styles.contentShell}>
          <View style={[styles.fullBleed, { backgroundColor: colors.background }]}> 
            {body}
          </View>
        </View>
      </View>
      {showTabBar && (
        <BottomTabBar
          activeTab={activeTab}
          onTabPress={setActiveTab}
          urgentCount={urgentCount}
        />
      )}
      <RiskChallengeSheet
        challenge={selectedChallenge}
        visible={Boolean(selectedChallenge)}
        busyActionType={control.actingActionType}
        onClose={() => setSelectedChallenge(null)}
        onConfirm={(challenge) => handleConfirmChallenge(challenge).catch(() => undefined)}
        onReject={(challengeId) => handleRejectChallenge(challengeId).catch(() => undefined)}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
  },
  main: {
    flex: 1,
    flexDirection: 'row',
  },
  contentShell: {
    flex: 1,
  },
  fullBleed: {
    flex: 1,
  },
});
