import { Platform } from 'react-native';

export async function verifyLocalBiometric(promptMessage: string): Promise<string> {
  if (Platform.OS === 'web') {
    return 'web_manual_confirm';
  }
  let LocalAuthentication: typeof import('expo-local-authentication') | null = null;
  try {
    LocalAuthentication = await import('expo-local-authentication');
  } catch {
    LocalAuthentication = null;
  }
  if (!LocalAuthentication) {
    return 'device_unlock_fallback';
  }
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const enrolled = hasHardware ? await LocalAuthentication.isEnrolledAsync() : false;
  if (!hasHardware || !enrolled) {
    return 'device_unlock_fallback';
  }
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage,
    cancelLabel: 'Cancel',
    fallbackLabel: 'Use device unlock',
  });
  if (!result.success) {
    throw new Error('Biometric verification was cancelled.');
  }
  return 'biometric_local';
}
