import React from 'react';
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { SurfaceHeader } from '@/components/SurfaceCard';
import { VaultProviderKeys, VaultStatus } from '@/types/companion';

export function VaultSettingsCard({
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
  return (
    <View style={styles.section}>
      <SurfaceHeader title="Secure Vault" subtitle="Unlock provider-backed actions from the phone after a remote restart." />
      <Text style={styles.status}>
        {vaultStatus?.is_setup === false
          ? 'Vault is not set up on this Axon server.'
          : vaultStatus?.is_unlocked
            ? `Unlocked · ${Math.max(0, Math.floor((vaultStatus?.ttl_remaining || 0) / 60))} min left`
            : 'Locked'}
      </Text>
      {vaultStatus && 'biometric_reunlock_available' in vaultStatus && (vaultStatus as Record<string, unknown>).biometric_reunlock_available ? (
        <Text style={styles.hint}>
          Trusted-device biometric re-unlock is available on this phone until {String((vaultStatus as Record<string, unknown>).biometric_reunlock_expires_at || '').replace('T', ' ').replace('Z', ' UTC')}.
        </Text>
      ) : vaultStatus && 'biometric_reunlock_enabled' in vaultStatus && (vaultStatus as Record<string, unknown>).biometric_reunlock_enabled ? (
        <Text style={styles.hint}>Biometric re-unlock was enabled before, but it has expired and needs one full password + TOTP unlock again.</Text>
      ) : (
        <Text style={styles.hint}>After one successful password + TOTP unlock on this device, Axon can allow biometric re-unlock as a trusted-device fallback if TOTP is unavailable.</Text>
      )}
      <View style={styles.pills}>
        {Object.keys(vaultProviderKeys?.resolved || {}).map((providerKey) => (
          <View key={providerKey} style={styles.pill}>
            <Text style={styles.pillText}>{providerKey}</Text>
          </View>
        ))}
      </View>
      {vaultStatus?.is_unlocked ? null : (
        <>
          <TextInput
            value={vaultMasterPassword}
            onChangeText={onChangeVaultMasterPassword}
            placeholder="Vault master password"
            placeholderTextColor="#7b8aa3"
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            style={styles.input}
          />
          <TextInput
            value={vaultTotpCode}
            onChangeText={onChangeVaultTotpCode}
            placeholder="TOTP code"
            placeholderTextColor="#7b8aa3"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="number-pad"
            style={styles.input}
          />
          <View style={styles.row}>
            <Text style={styles.label}>Keep vault unlocked for 24 hours</Text>
            <Switch value={Boolean(vaultRememberMe)} onValueChange={onChangeVaultRememberMe} />
          </View>
        </>
      )}
      {vaultError ? <Text style={styles.errorText}>{vaultError}</Text> : null}
      <View style={styles.actions}>
        <Pressable style={[styles.button, vaultBusy ? styles.buttonDisabled : null]} disabled={vaultBusy} onPress={onRefreshVault}>
          <Text style={styles.buttonText}>Refresh vault</Text>
        </Pressable>
        {vaultStatus?.is_unlocked ? (
          <Pressable style={[styles.button, vaultBusy ? styles.buttonDisabled : null]} disabled={vaultBusy} onPress={onLockVault}>
            <Text style={styles.buttonText}>{vaultBusy ? 'Working…' : 'Lock vault'}</Text>
          </Pressable>
        ) : (
          <>
            <Pressable style={[styles.button, vaultBusy ? styles.buttonDisabled : null]} disabled={vaultBusy} onPress={onUnlockVault}>
              <Text style={styles.buttonText}>{vaultBusy ? 'Unlocking…' : 'Unlock with password + TOTP'}</Text>
            </Pressable>
            {vaultStatus && 'biometric_reunlock_available' in vaultStatus && (vaultStatus as Record<string, unknown>).biometric_reunlock_available ? (
              <Pressable style={[styles.button, vaultBusy ? styles.buttonDisabled : null]} disabled={vaultBusy} onPress={onUnlockVaultWithBiometrics}>
                <Text style={styles.buttonText}>{vaultBusy ? 'Unlocking…' : 'Unlock with biometrics'}</Text>
              </Pressable>
            ) : null}
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: 10,
    borderTopWidth: 1,
    borderTopColor: '#1a2437',
    paddingTop: 8,
  },
  status: {
    color: '#cbd5e1',
    fontSize: 12,
    lineHeight: 18,
  },
  hint: {
    color: '#94a3b8',
    fontSize: 11,
    lineHeight: 17,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  pill: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: '#0b1627',
  },
  pillText: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '700',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  label: {
    color: '#e5eefb',
    fontSize: 13,
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
  actions: {
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
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#7dd3fc',
    fontSize: 12,
    fontWeight: '700',
  },
  errorText: {
    color: '#fca5a5',
    fontSize: 12,
    lineHeight: 18,
  },
});
