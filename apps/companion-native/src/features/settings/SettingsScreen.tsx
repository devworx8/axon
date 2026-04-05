import React from 'react';
import { Linking, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { MetricCard } from '@/components/MetricCard';
import { CompanionSettings } from './useSettings';
import { VaultProviderKeys, VaultStatus } from '@/types/companion';
import { AxonVoiceSettingsCard } from './AxonVoiceSettingsCard';
import { VaultSettingsCard } from './VaultSettingsCard';
import type { AxonModeStatus } from '@/types/axon';

export function SettingsScreen({
  settings,
  apiBaseUrl,
  onChangeApiBaseUrl,
  onToggleVoice,
  onToggleListening,
  onToggleSpokenReplies,
  onToggleAxonMode,
  onChangeAxonWakePhrase,
  onToggleAxonBootSound,
  onToggleContinuousForegroundMonitoring,
  onChangeAxonVoiceProvider,
  onChangeAxonVoiceIdentity,
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
  axonStatus,
}: {
  settings: CompanionSettings;
  apiBaseUrl: string;
  onChangeApiBaseUrl: (value: string) => void;
  onToggleVoice: (value: boolean) => void;
  onToggleListening: (value: boolean) => void;
  onToggleSpokenReplies: (value: boolean) => void;
  onToggleAxonMode: (value: boolean) => void;
  onChangeAxonWakePhrase: (value: string) => void;
  onToggleAxonBootSound: (value: boolean) => void;
  onToggleContinuousForegroundMonitoring: (value: boolean) => void;
  onChangeAxonVoiceProvider: (value: 'cloud' | 'local' | 'device') => void;
  onChangeAxonVoiceIdentity: (value: string) => void;
  vaultStatus?: VaultStatus | null;
  vaultProviderKeys?: VaultProviderKeys | null;
  vaultBusy?: boolean;
  vaultError?: string | null;
  vaultMasterPassword?: string;
  vaultTotpCode?: string;
  vaultRememberMe?: boolean;
  onChangeVaultMasterPassword: (value: string) => void;
  onChangeVaultTotpCode: (value: string) => void;
  onChangeVaultRememberMe: (value: boolean) => void;
  onRefreshVault: () => void;
  onUnlockVault: () => void;
  onUnlockVaultWithBiometrics: () => void;
  onLockVault: () => void;
  axonStatus?: AxonModeStatus | null;
}) {
  const providerCount = Object.keys(vaultProviderKeys?.resolved || {}).length;
  const trimmedBaseUrl = String(apiBaseUrl || '').trim();
  const canOpenDesktop = Boolean(trimmedBaseUrl);
  const openDesktop = () => {
    if (!trimmedBaseUrl) return;
    const url = trimmedBaseUrl.startsWith('http') ? trimmedBaseUrl : `http://${trimmedBaseUrl}`;
    Linking.openURL(url).catch(() => undefined);
  };

  return (
    <View style={styles.stack}>
      <SurfaceCard>
        <SurfaceHeader title="Settings" subtitle="Keep Axon Online tuned and trustworthy on this device." />
        <View style={styles.metrics}>
          <MetricCard label="Vault" value={vaultStatus?.is_unlocked ? 'Unlocked' : 'Locked'} accent={vaultStatus?.is_unlocked ? 'success' : 'warn'} />
          <MetricCard label="Provider keys" value={providerCount} accent={providerCount ? 'accent' : 'neutral'} />
        </View>
        <Text style={styles.helper}>
          Use this screen for device-level behavior and voice. Backend models and connectors stay managed in the desktop console.
        </Text>
      </SurfaceCard>

      <SurfaceCard>
        <SurfaceHeader title="Backend link" subtitle="Point this device at the live Axon desktop." />
        <TextInput
          value={apiBaseUrl}
          onChangeText={onChangeApiBaseUrl}
          placeholder="Axon desktop URL, e.g. http://192.168.1.50:7734"
          placeholderTextColor="#7b8aa3"
          autoCapitalize="none"
          autoCorrect={false}
          inputMode="url"
          keyboardType="url"
          textContentType="URL"
          style={styles.input}
        />
        <View style={styles.actionRow}>
          <Pressable
            onPress={openDesktop}
            disabled={!canOpenDesktop}
            style={({ pressed }) => [
              styles.button,
              !canOpenDesktop ? styles.buttonDisabled : null,
              pressed && canOpenDesktop ? styles.buttonPressed : null,
            ]}
          >
            <Text style={styles.buttonText}>Open Axon desktop</Text>
          </Pressable>
          <Pressable style={styles.ghostButton}>
            <Text style={styles.ghostText}>Desktop manages providers</Text>
          </Pressable>
        </View>
      </SurfaceCard>

      <AxonVoiceSettingsCard
        settings={settings}
        axonStatus={axonStatus}
        onToggleVoice={onToggleVoice}
        onToggleListening={onToggleListening}
        onToggleSpokenReplies={onToggleSpokenReplies}
        onToggleAxonMode={onToggleAxonMode}
        onChangeAxonWakePhrase={onChangeAxonWakePhrase}
        onToggleAxonBootSound={onToggleAxonBootSound}
        onToggleContinuousForegroundMonitoring={onToggleContinuousForegroundMonitoring}
        onChangeAxonVoiceProvider={onChangeAxonVoiceProvider}
        onChangeAxonVoiceIdentity={onChangeAxonVoiceIdentity}
      />

      <VaultSettingsCard
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
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 14,
  },
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  actionRow: {
    marginTop: 10,
    gap: 10,
  },
  button: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#22304a',
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: '#0f1d31',
  },
  input: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#e5eefb',
    backgroundColor: '#0b1627',
    fontSize: 13,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonPressed: {
    opacity: 0.85,
  },
  buttonText: {
    color: '#7dd3fc',
    fontSize: 12,
    fontWeight: '700',
  },
  ghostButton: {
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: 'rgba(125, 211, 252, 0.2)',
    alignItems: 'center',
  },
  ghostText: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '600',
  },
  helper: {
    marginTop: 10,
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 18,
  },
});
