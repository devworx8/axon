import React, { useEffect, useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';

import { fetchCompanionIdentity } from '@/api/companion';
import {
  fetchMobileVaultProviderKeys,
  fetchMobileVaultStatus,
  lockMobileVault,
  unlockMobileVault,
  unlockMobileVaultWithBiometric,
} from '@/api/vault';
import { AppTabBar } from '@/components/AppTabBar';
import { useAxonMobileRuntime } from '@/features/axon/useAxonMobileRuntime';
import { useAuth } from '@/features/auth/useAuth';
import { useMobileControl } from '@/features/control/useMobileControl';
import { useMissionControl } from '@/features/mission/useMissionControl';
import { usePresence } from '@/features/presence/usePresence';
import { RiskChallengeSheet } from '@/features/session/RiskChallengeSheet';
import { loadCompanionConfig, saveCompanionConfig } from '@/features/settings/configStore';
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
  const [activeTab, setActiveTab] = useState<TabKey>('mission');
  const [config, setConfig] = useState<CompanionConfig>({ apiBaseUrl: '', workspaceId: null, sessionId: null, deviceId: null });
  const [configReady, setConfigReady] = useState(false);
  const [deviceName, setDeviceName] = useState('Axon phone');
  const [pairingPin, setPairingPin] = useState('');
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [verifiedPairing, setVerifiedPairing] = useState(false);
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
  const voice = useVoice(config, (nextSession) => {
    setConfig((current) => ({
      ...current,
      sessionId: nextSession.id,
      workspaceId: nextSession.workspace_id ?? current.workspaceId ?? null,
    }));
  });

  useEffect(() => {
    let cancelled = false;
    loadCompanionConfig()
      .then((stored) => {
        if (cancelled) return;
        setConfig({
          apiBaseUrl: stored.apiBaseUrl || '',
          workspaceId: stored.workspaceId ?? null,
          sessionId: stored.sessionId ?? null,
          deviceId: stored.deviceId ?? null,
          deviceKey: stored.deviceKey || '',
          deviceName: stored.deviceName || '',
          accessToken: stored.accessToken || '',
          tokenPair: stored.tokenPair,
        });
        if (stored.deviceName) {
          setDeviceName(stored.deviceName);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setConfigReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!configReady) return;
    saveCompanionConfig(config).catch(() => undefined);
  }, [config, configReady]);

  useEffect(() => {
    if (!config.accessToken) return;
    let cancelled = false;

    (async () => {
      try {
        const identity = await fetchCompanionIdentity(config);
        if (!identity.device || !identity.auth_session) {
          throw new Error('Axon Online pairing expired. Pair this device again.');
        }
        if (cancelled) return;
        setVerifiedPairing(true);
        setBootstrapError(null);
        const nextDevice = identity.device || null;
        const nextSession = (identity.sessions || [])[0] || null;
        setConfig((current) => ({
          ...current,
          deviceId: nextDevice?.id ?? current.deviceId ?? null,
          deviceKey: nextDevice?.device_key || current.deviceKey || '',
          deviceName: nextDevice?.name || current.deviceName || '',
          sessionId: nextSession?.id ?? current.sessionId ?? null,
          workspaceId: nextSession?.workspace_id ?? current.workspaceId ?? null,
          apiBaseUrl: current.apiBaseUrl || '',
        }));
        if (nextDevice?.name) {
          setDeviceName(nextDevice.name);
        }
        if (identity.presence) {
          presence.setPresence(identity.presence);
        }
        const settled = await Promise.allSettled([
          mission.refresh(nextSession?.workspace_id ?? config.workspaceId ?? null, nextSession?.id ?? config.sessionId ?? null),
          control.refresh(),
          (async () => {
            const [status, providerKeys] = await Promise.all([
              fetchMobileVaultStatus(config),
              fetchMobileVaultProviderKeys(config),
            ]);
            if (cancelled) return;
            setVaultStatus(status);
            setVaultProviderKeys(providerKeys);
          })(),
        ]);
        if (cancelled) return;
        const failed = settled.find((item) => item.status === 'rejected') as PromiseRejectedResult | undefined;
        if (failed?.reason) {
          setBootstrapError(failed.reason instanceof Error ? failed.reason.message : 'Axon Online could not load Mission Control.');
        }
      } catch (err) {
        if (!cancelled) {
          setVerifiedPairing(false);
          setBootstrapError(err instanceof Error ? err.message : 'Unable to reach live Axon.');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [config.accessToken, config.apiBaseUrl]);

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

  useEffect(() => {
    if (!config.accessToken) return;
    const timer = setInterval(() => {
      mission.refresh().catch(() => undefined);
      control.refresh().catch(() => undefined);
      fetchMobileVaultStatus(config).then(setVaultStatus).catch(() => undefined);
      fetchMobileVaultProviderKeys(config).then(setVaultProviderKeys).catch(() => undefined);
    }, 6000);
    return () => clearInterval(timer);
  }, [config, config.accessToken, control.refresh, mission.refresh]);

  const activeSession = mission.snapshot?.sessions?.[0] || null;
  const currentWorkspaceLabel = mission.snapshot?.focus?.workspace?.name || undefined;
  const attentionSummary = mission.snapshot?.attention?.summary || EMPTY_ATTENTION;
  const attentionInbox = mission.snapshot?.attention?.inbox || EMPTY_INBOX;
  const currentWorkspaceId = config.workspaceId ?? mission.snapshot?.focus?.workspace?.id ?? null;
  const currentSessionId = config.sessionId ?? activeSession?.id ?? null;
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
    ['mission', 'Mission Control'],
    ['voice', 'Voice'],
    ['attention', 'Attention'],
    ['projects', 'Projects'],
    ['sessions', 'Sessions'],
    ['settings', 'Settings'],
  ] as const), []);
  const body = (
    <AppNavigatorBody
      activeTab={activeTab}
      config={config}
      colors={colors}
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
      onSubmitCommand={handleVoiceSubmit}
      onExecuteAction={(actionType, payload) => handleExecuteAction(actionType, payload).catch(() => undefined)}
      onApprovePending={() => handleApprovePending().catch(() => undefined)}
      onConfirmChallenge={(challenge) => handleConfirmChallenge(challenge).catch(() => undefined)}
      onRejectChallenge={(challengeId) => handleRejectChallenge(challengeId).catch(() => undefined)}
      onOpenChallenge={setSelectedChallenge}
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
      verifiedPairing={verifiedPairing}
      axon={{ status: axonMode.status, busy: axonMode.busy }}
      axonError={axonMode.error}
      onArmAxon={() => handleArmAxon().catch(() => undefined)}
      onDisarmAxon={() => handleDisarmAxon().catch(() => undefined)}
      onResumeSession={activeSession ? () => handleExecuteAction('session.resume', { session_key: activeSession.session_key, agent_session_id: activeSession.agent_session_id }).catch(() => undefined) : undefined}
      onStopSession={activeSession ? () => handleExecuteAction('session.stop').catch(() => undefined) : undefined}
    />
  );

  const statusLabel = verifiedPairing
    ? String(mission.snapshot?.posture || 'healthy').replace('_', ' ')
    : (config.accessToken ? 'Saved locally' : 'Not paired');
  const statusColor = verifiedPairing
    ? (mission.snapshot?.posture === 'urgent' ? colors.danger : mission.snapshot?.posture === 'degraded' ? colors.warning : colors.success)
    : (config.accessToken ? colors.warning : colors.muted);

  return (
    <KeyboardAvoidingView
      style={styles.shell}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={styles.topBar}>
        <View style={styles.topBarText}>
          <Text style={[styles.brand, { color: colors.text }]}>Axon</Text>
          <Text style={[styles.subbrand, { color: colors.muted }]}>Online</Text>
        </View>
        <View style={[styles.statusBadge, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Text style={[styles.statusText, { color: statusColor }]}>{statusLabel}</Text>
        </View>
      </View>

      <View style={styles.tabRail}>
        <AppTabBar
          tabs={tabs.map(([key, label]) => ({ key, label }))}
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as TabKey)}
        />
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.stack}>{body}</View>
      </ScrollView>
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
  topBar: {
    paddingHorizontal: 18,
    paddingTop: 12,
    paddingBottom: 4,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  topBarText: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 8,
  },
  statusBadge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  brand: {
    fontSize: 26,
    fontWeight: '800',
    letterSpacing: -0.4,
  },
  subbrand: {
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 1.2,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  tabRail: {
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  content: {
    paddingHorizontal: 16,
    paddingBottom: 28,
  },
  stack: {
    gap: 14,
  },
  heroKicker: {
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 1.1,
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: '800',
  },
  heroText: {
    marginTop: 8,
    fontSize: 14,
    lineHeight: 20,
  },
});
