import type { CompanionLinkState } from '@/features/auth/sessionState';

type TabKey = 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings';

export function sessionGateCopy(activeTab: TabKey, linkState: CompanionLinkState) {
  if (linkState === 'offline') {
    if (activeTab === 'voice') {
      return {
        title: 'Axon voice is offline',
        subtitle: 'The desktop runtime is unreachable, so voice commands cannot hit the protected control path right now.',
        detail: 'Keep the trusted link. Axon will reconnect when the desktop app is reachable again.',
      };
    }
    return {
      title: 'Axon is offline',
      subtitle: 'This phone is still paired, but the desktop runtime is not reachable right now.',
      detail: 'Protected routes stay paused until Axon reconnects. You do not need to pair again unless the device trust was revoked.',
    };
  }
  if (activeTab === 'voice') {
    return {
      title: 'Reconnect Axon voice',
      subtitle: 'Voice capture and Axon mode need a verified companion session before this phone can call protected routes.',
      detail: 'If the saved session expired or this device was revoked, pair again and Voice will resume from the same mobile shell.',
    };
  }
  return {
    title: 'Pair your mobile operator',
    subtitle: 'Link this device to live Axon first, then your phone can act like a real command center.',
    detail: 'Protected routes stay locked until Axon verifies the saved mobile session.',
  };
}

export function activeGateError(authError?: string | null, bootstrapError?: string | null) {
  return authError || bootstrapError || null;
}
