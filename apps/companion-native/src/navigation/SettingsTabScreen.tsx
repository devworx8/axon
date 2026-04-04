import React from 'react';

import { SettingsScreen } from '@/features/settings/SettingsScreen';

export function SettingsTabScreen({
  settings,
  config,
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
  settings: any;
  config: any;
  vaultStatus: any;
  vaultProviderKeys: any;
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
}) {
  return (
    <SettingsScreen
      settings={settings.settings}
      apiBaseUrl={config.apiBaseUrl || ''}
      onChangeApiBaseUrl={settings.setApiBaseUrl}
      onToggleVoice={(value) => settings.setSettings((current: any) => ({ ...current, voiceEnabled: value }))}
      onToggleListening={(value) => settings.setSettings((current: any) => ({ ...current, alwaysListening: value }))}
      onToggleSpokenReplies={(value) => settings.setSettings((current: any) => ({ ...current, spokenReplies: value }))}
      onToggleAxonMode={(value) => settings.setSettings((current: any) => ({ ...current, axonModeEnabled: value }))}
      onChangeAxonWakePhrase={(value) => settings.setSettings((current: any) => ({ ...current, axonWakePhrase: value }))}
      onToggleAxonBootSound={(value) => settings.setSettings((current: any) => ({ ...current, axonBootSound: value }))}
      onToggleContinuousForegroundMonitoring={(value) => settings.setSettings((current: any) => ({ ...current, continuousForegroundMonitoring: value }))}
      onChangeAxonVoiceProvider={(value) => settings.setSettings((current: any) => ({ ...current, axonVoiceProvider: value }))}
      onChangeAxonVoiceIdentity={(value) => settings.setSettings((current: any) => ({ ...current, axonVoiceIdentity: value }))}
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
}
