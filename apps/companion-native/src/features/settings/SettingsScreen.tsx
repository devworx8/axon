import React from 'react';
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { MetricCard } from '@/components/MetricCard';
import { CompanionSettings } from './useSettings';
import { VaultProviderKeys, VaultStatus } from '@/types/companion';
import { AxonVoiceSettingsCard } from './AxonVoiceSettingsCard';
import { VaultSettingsCard } from './VaultSettingsCard';

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
}) {
  const providerCount = Object.keys(vaultProviderKeys?.resolved || {}).length;

  return (
    <SurfaceCard>
      <SurfaceHeader title="Settings" subtitle="Axon Online preferences and live voice behavior." />
      <View style={styles.metrics}>
        <MetricCard label="Vault" value={vaultStatus?.is_unlocked ? 'Unlocked' : 'Locked'} accent={vaultStatus?.is_unlocked ? 'success' : 'warn'} />
        <MetricCard label="Provider keys" value={providerCount} accent={providerCount ? 'accent' : 'neutral'} />
      </View>
      <AxonVoiceSettingsCard
        settings={settings}
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
      <TextInput
        value={apiBaseUrl}
        onChangeText={onChangeApiBaseUrl}
        placeholder="Axon desktop URL, e.g. http://192.168.1.50:7734"
        placeholderTextColor="#7b8aa3"
        autoCapitalize="none"
        autoCorrect={false}
        style={styles.input}
      />
      <Pressable style={styles.button}>
        <Text style={styles.buttonText}>Edit backend settings in Axon desktop</Text>
      </Pressable>
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
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  button: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#22304a',
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  input: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#e5eefb',
    backgroundColor: '#0b1627',
    fontSize: 12,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#7dd3fc',
    fontSize: 12,
    fontWeight: '700',
  },
});
