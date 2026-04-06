import type { CompanionLinkState } from '@/features/auth/sessionState';

export type CompanionLinkTone = 'success' | 'warning' | 'danger' | 'muted';

export function companionLinkStatusLabel(linkState: CompanionLinkState, posture?: string | null): string {
  switch (linkState) {
    case 'checking':
      return 'Checking link';
    case 'linked':
      return String(posture || 'healthy').replace('_', ' ');
    case 'offline':
      return 'Offline';
    case 'repair_required':
      return 'Repair required';
    default:
      return 'Not paired';
  }
}

export function companionLinkStatusTone(linkState: CompanionLinkState, posture?: string | null): CompanionLinkTone {
  switch (linkState) {
    case 'checking':
      return 'warning';
    case 'linked':
      if (posture === 'urgent') {
        return 'danger';
      }
      if (posture === 'degraded') {
        return 'warning';
      }
      return 'success';
    case 'offline':
    case 'repair_required':
      return 'warning';
    default:
      return 'muted';
  }
}

export function shouldShowCompanionTabBar(linkState: CompanionLinkState, hasStoredPairing: boolean): boolean {
  return linkState !== 'unpaired' || hasStoredPairing;
}
