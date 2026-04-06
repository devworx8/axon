import React from 'react';

import { SettingsScreen } from '@/features/settings/SettingsScreen';
import type { CompanionConfig, VaultStatus, VaultProviderKeys } from '@/types/companion-core';
import type { AxonModeStatus } from '@/types/axon';
import type { CompanionSettings } from '@/features/settings/useSettings';

type SettingsHook = {
  settings: CompanionSettings;
  setSettings: React.Dispatch<React.SetStateAction<CompanionSettings>>;
  setApiBaseUrl: (url: string) => void;
};

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
  onCopyAccessToken,
  onRePair,
  axonStatus,
}: {
  settings: SettingsHook;
  config: CompanionConfig;
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
  axonStatus?: AxonModeStatus | null;
}) {
  return (
    <SettingsScreen
      settings={settings.settings}
      apiBaseUrl={config.apiBaseUrl || ''}
      onChangeApiBaseUrl={settings.setApiBaseUrl}
      onToggleVoice={(value) => settings.setSettings((current) => ({ ...current, voiceEnabled: value }))}
      onToggleListening={(value) => settings.setSettings((current) => ({ ...current, alwaysListening: value }))}
      onToggleSpokenReplies={(value) => settings.setSettings((current) => ({ ...current, spokenReplies: value }))}
      onToggleAxonMode={(value) => settings.setSettings((current) => ({ ...current, axonModeEnabled: value }))}
      onChangeAxonWakePhrase={(value) => settings.setSettings((current) => ({ ...current, axonWakePhrase: value }))}
      onToggleAxonBootSound={(value) => settings.setSettings((current) => ({ ...current, axonBootSound: value }))}
      onToggleContinuousForegroundMonitoring={(value) => settings.setSettings((current) => ({ ...current, continuousForegroundMonitoring: value }))}
      onChangeAxonVoiceProvider={(value) => settings.setSettings((current) => ({ ...current, axonVoiceProvider: value }))}
      onChangeAxonVoiceIdentity={(value) => settings.setSettings((current) => ({ ...current, axonVoiceIdentity: value }))}
      onChangeAzureSpeechKey={(value) => settings.setSettings((current) => ({ ...current, azureSpeechKey: value }))}
      onChangeAzureSpeechRegion={(value) => settings.setSettings((current) => ({ ...current, azureSpeechRegion: value }))}
      onChangeFastVoiceRuntimeMode={(value) => settings.setSettings((current) => ({ ...current, fastVoiceRuntimeMode: value }))}
      onChangeVoiceSpeechRate={(value) => settings.setSettings((current) => ({ ...current, voiceSpeechRate: value }))}
      onChangeVoiceSpeechPitch={(value) => settings.setSettings((current) => ({ ...current, voiceSpeechPitch: value }))}
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
      axonStatus={axonStatus}
    />
  );
}
