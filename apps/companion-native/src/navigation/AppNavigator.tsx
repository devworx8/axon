import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { fetchCompanionIdentity } from '@/api/companion';
import { AttentionScreen } from '@/features/attention/AttentionScreen';
import { useAttention } from '@/features/attention/useAttention';
import { AuthScreen } from '@/features/auth/AuthScreen';
import { useAuth } from '@/features/auth/useAuth';
import { PresenceScreen } from '@/features/presence/PresenceScreen';
import { usePresence } from '@/features/presence/usePresence';
import { SessionScreen } from '@/features/session/SessionScreen';
import { useSession } from '@/features/session/useSession';
import { SettingsScreen } from '@/features/settings/SettingsScreen';
import { loadCompanionConfig, saveCompanionConfig } from '@/features/settings/configStore';
import { useSettings } from '@/features/settings/useSettings';
import { VoiceScreen } from '@/features/voice/VoiceScreen';
import { useVoice } from '@/features/voice/useVoice';
import { WorkspaceScreen } from '@/features/workspace/WorkspaceScreen';
import { useWorkspace } from '@/features/workspace/useWorkspace';
import { SurfaceCard } from '@/components/SurfaceCard';
import { useTheme } from '@/theme/ThemeProvider';
import { CompanionConfig } from '@/types/companion';

type TabKey = 'home' | 'attention' | 'voice' | 'workspace' | 'session' | 'settings';

export function AppNavigator() {
  const { colors } = useTheme();
  const [activeTab, setActiveTab] = useState<TabKey>('home');
  const [config, setConfig] = useState<CompanionConfig>({ workspaceId: null, sessionId: null, deviceId: null });
  const [configReady, setConfigReady] = useState(false);
  const [deviceName, setDeviceName] = useState('Axon phone');
  const [pairingPin, setPairingPin] = useState('');

  const auth = useAuth(config, setConfig);
  const presence = usePresence(config);
  const attention = useAttention(config);
  const workspace = useWorkspace(config);
  const session = useSession(config);
  const settings = useSettings(config, setConfig);
  const voice = useVoice(config, (nextSession) => {
    session.setActiveSession(nextSession);
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
        if (cancelled) return;
        const nextDevice = identity.device || null;
        const nextSession = (identity.sessions || [])[0] || null;
        if (nextDevice || nextSession) {
          setConfig((current) => ({
            ...current,
            deviceId: nextDevice?.id ?? current.deviceId ?? null,
            deviceKey: nextDevice?.device_key || current.deviceKey || '',
            deviceName: nextDevice?.name || current.deviceName || '',
            sessionId: nextSession?.id ?? current.sessionId ?? null,
            workspaceId: nextSession?.workspace_id ?? current.workspaceId ?? null,
          }));
          if (nextDevice?.name) {
            setDeviceName(nextDevice.name);
          }
        }
        if (identity.presence) {
          presence.setPresence(identity.presence);
        }
        if (identity.sessions?.length) {
          session.setSessions(identity.sessions);
          session.setActiveSession(identity.sessions[0]);
        }
      } catch {
        // leave the local shell usable even if identity bootstrap fails
      }

      await Promise.allSettled([
        attention.refresh(),
        workspace.refresh(),
        session.refresh(),
        presence.refresh(),
      ]);
    })();

    return () => {
      cancelled = true;
    };
  }, [config.accessToken]);

  useEffect(() => {
    if (!config.accessToken) return;
    presence.heartbeat(config.workspaceId ?? null, config.sessionId ?? null).catch(() => undefined);
  }, [config.accessToken, config.workspaceId, config.sessionId]);

  const tabs = useMemo(() => ([
    ['home', 'Home'],
    ['attention', 'Attention'],
    ['voice', 'Voice'],
    ['workspace', 'Workspaces'],
    ['session', 'Session'],
    ['settings', 'Settings'],
  ] as const), []);

  const body = useMemo(() => {
    switch (activeTab) {
      case 'attention':
        return (
          <AttentionScreen
            summary={attention.summary}
            items={[...attention.inbox.now, ...attention.inbox.waiting_on_me, ...attention.inbox.watch]}
            onResolve={(id) => attention.resolveItem(id).catch(() => undefined)}
          />
        );
      case 'voice':
        return (
          <VoiceScreen
            onSubmit={(text) => voice.submitVoiceTurn(text).catch(() => undefined)}
            sending={voice.sending}
            transcript={voice.lastTranscript}
            response={voice.responseText}
          />
        );
      case 'workspace':
        return <WorkspaceScreen workspaces={workspace.workspaces} />;
      case 'session':
        return <SessionScreen session={session.activeSession} />;
      case 'settings':
        return (
          <SettingsScreen
            settings={settings.settings}
            onToggleVoice={(value) => settings.setSettings(current => ({ ...current, voiceEnabled: value }))}
            onToggleListening={(value) => settings.setSettings(current => ({ ...current, alwaysListening: value }))}
          />
        );
      case 'home':
      default:
        return (
          <>
            <SurfaceCard>
              <Text style={[styles.heroTitle, { color: colors.text }]}>Axon Companion</Text>
              <Text style={[styles.heroText, { color: colors.muted }]}>Voice, attention, workspace presence, and session continuity in one thin native shell.</Text>
            </SurfaceCard>
            <AuthScreen
              deviceName={deviceName}
              onChangeDeviceName={setDeviceName}
              pairingPin={pairingPin}
              onChangePairingPin={setPairingPin}
              onPair={() => auth.pair(deviceName, pairingPin).catch(() => undefined)}
              pairing={auth.pairing}
              error={auth.error}
            />
            <PresenceScreen presence={presence.presence} />
          </>
        );
    }
  }, [activeTab, attention, auth, colors.muted, colors.text, deviceName, presence.presence, session.activeSession, settings, voice.lastTranscript, voice.responseText, voice.sending, workspace.workspaces]);

  return (
    <View style={styles.shell}>
      <View style={styles.topBar}>
        <Text style={[styles.brand, { color: colors.text }]}>Axon</Text>
        <Text style={[styles.subbrand, { color: colors.muted }]}>Companion</Text>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.stack}>{body}</View>
      </ScrollView>

      <View style={[styles.tabs, { borderTopColor: colors.border, backgroundColor: colors.surface }]}>
        {tabs.map(([key, label]) => (
          <Pressable key={key} onPress={() => setActiveTab(key)} style={styles.tab}>
            <Text style={[styles.tabText, activeTab === key && styles.tabTextActive]}>{label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
  },
  topBar: {
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 8,
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 8,
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
  content: {
    paddingHorizontal: 16,
    paddingBottom: 90,
  },
  stack: {
    gap: 14,
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
  tabs: {
    borderTopWidth: 1,
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingVertical: 10,
  },
  tab: {
    paddingVertical: 6,
    paddingHorizontal: 8,
  },
  tabText: {
    color: '#7f93ad',
    fontSize: 12,
    fontWeight: '700',
  },
  tabTextActive: {
    color: '#6ee7ff',
  },
});
