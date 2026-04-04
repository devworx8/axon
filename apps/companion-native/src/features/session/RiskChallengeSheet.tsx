import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { RiskChallenge } from '@/types/companion';

function detailFromChallenge(challenge: RiskChallenge | null) {
  if (!challenge?.request_json) return '';
  try {
    const payload = JSON.parse(challenge.request_json) as Record<string, unknown>;
    const parts = Object.entries(payload)
      .filter(([, value]) => value !== null && value !== '')
      .slice(0, 4)
      .map(([key, value]) => `${key}: ${String(value)}`);
    return parts.join(' • ');
  } catch {
    return '';
  }
}

export function RiskChallengeSheet({
  challenge,
  visible,
  busyActionType,
  onClose,
  onConfirm,
  onReject,
}: {
  challenge: RiskChallenge | null;
  visible: boolean;
  busyActionType?: string | null;
  onClose: () => void;
  onConfirm: (challenge: RiskChallenge) => void;
  onReject: (challengeId: number) => void;
}) {
  const requestDetail = detailFromChallenge(challenge);
  const busy = challenge
    ? busyActionType === `confirm:${challenge.action_type}` || busyActionType === `reject:${challenge.id}`
    : false;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <View style={styles.sheet}>
          <Text style={styles.kicker}>Protected action</Text>
          <Text style={styles.title}>{challenge?.title || challenge?.action_type || 'Risk challenge'}</Text>
          <Text style={styles.detail}>
            {challenge?.summary || 'This action needs trusted-device confirmation before Axon can continue.'}
          </Text>
          <View style={styles.pills}>
            {challenge?.risk_tier ? <StatusPill label={String(challenge.risk_tier)} tone="danger" /> : null}
            {challenge?.requires_biometric ? <StatusPill label="Biometric" tone="warn" /> : null}
            {challenge?.status ? <StatusPill label={String(challenge.status)} tone="neutral" /> : null}
          </View>
          {requestDetail ? <Text style={styles.meta}>{requestDetail}</Text> : null}
          <Text style={styles.note}>
            Confirming will create an immutable action receipt and may prompt for trusted-device elevation first.
          </Text>
          <View style={styles.actions}>
            <Pressable onPress={() => challenge && onConfirm(challenge)} disabled={busy || !challenge} style={[styles.primaryAction, busy ? styles.disabled : null]}>
              <Text style={styles.primaryText}>{busy ? 'Working…' : 'Confirm action'}</Text>
            </Pressable>
            <Pressable onPress={() => challenge && onReject(challenge.id)} disabled={busy || !challenge} style={[styles.secondaryAction, busy ? styles.disabled : null]}>
              <Text style={styles.secondaryText}>Reject</Text>
            </Pressable>
            <Pressable onPress={onClose} style={styles.ghostAction}>
              <Text style={styles.ghostText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(2, 6, 23, 0.55)',
  },
  backdrop: {
    flex: 1,
  },
  sheet: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 26,
    gap: 12,
    backgroundColor: '#08111f',
    borderTopWidth: 1,
    borderColor: '#22304a',
  },
  kicker: {
    color: '#fbbf24',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  title: {
    color: '#f8fafc',
    fontSize: 22,
    fontWeight: '800',
  },
  detail: {
    color: '#cbd5e1',
    fontSize: 14,
    lineHeight: 21,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  meta: {
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 18,
  },
  note: {
    color: '#7dd3fc',
    fontSize: 12,
    lineHeight: 18,
  },
  actions: {
    gap: 10,
  },
  primaryAction: {
    alignItems: 'center',
    borderRadius: 16,
    backgroundColor: '#fbbf24',
    paddingVertical: 14,
  },
  primaryText: {
    color: '#1a1203',
    fontWeight: '800',
  },
  secondaryAction: {
    alignItems: 'center',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#6b4f13',
    backgroundColor: '#2d2310',
    paddingVertical: 14,
  },
  secondaryText: {
    color: '#f8fafc',
    fontWeight: '700',
  },
  ghostAction: {
    alignItems: 'center',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0b1627',
    paddingVertical: 14,
  },
  ghostText: {
    color: '#e5eefb',
    fontWeight: '700',
  },
  disabled: {
    opacity: 0.6,
  },
});
