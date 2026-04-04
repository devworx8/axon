import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { RiskChallenge } from '@/types/companion';

export function ChallengeListCard({
  challenges,
  actingActionType,
  onOpen,
  onConfirm,
  onReject,
}: {
  challenges: RiskChallenge[];
  actingActionType?: string | null;
  onOpen?: (challenge: RiskChallenge) => void;
  onConfirm?: (challenge: RiskChallenge) => void;
  onReject?: (challengeId: number) => void;
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Protected actions" subtitle="Destructive or high-risk controls stay behind trusted-device challenge confirmation." />
      <View style={styles.stack}>
        {challenges.length ? challenges.map((challenge) => {
          const busy = actingActionType === `confirm:${challenge.action_type}` || actingActionType === `reject:${challenge.id}`;
          return (
            <View key={challenge.id} style={styles.row}>
              <View style={styles.meta}>
                <Text style={styles.title}>{challenge.title || challenge.action_type}</Text>
                <Text style={styles.detail}>{challenge.summary || 'This action needs explicit confirmation.'}</Text>
              </View>
              <View style={styles.pills}>
                <StatusPill label={String(challenge.risk_tier || 'destructive')} tone="danger" />
                {challenge.requires_biometric ? <StatusPill label="Biometric" tone="warn" /> : null}
              </View>
              <View style={styles.actions}>
                {onOpen ? (
                  <Pressable onPress={() => onOpen(challenge)} style={styles.reviewAction}>
                    <Text style={styles.reviewText}>Review</Text>
                  </Pressable>
                ) : null}
                {onConfirm ? (
                  <Pressable onPress={() => onConfirm(challenge)} disabled={busy} style={[styles.primaryAction, busy ? styles.disabled : null]}>
                    <Text style={styles.primaryText}>{busy ? 'Working…' : 'Confirm'}</Text>
                  </Pressable>
                ) : null}
                {onReject ? (
                  <Pressable onPress={() => onReject(challenge.id)} disabled={busy} style={[styles.secondaryAction, busy ? styles.disabled : null]}>
                    <Text style={styles.secondaryText}>Reject</Text>
                  </Pressable>
                ) : null}
              </View>
            </View>
          );
        }) : <Text style={styles.empty}>No destructive challenges are waiting right now.</Text>}
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 10,
  },
  row: {
    borderWidth: 1,
    borderColor: '#5f3f14',
    borderRadius: 16,
    padding: 12,
    gap: 8,
    backgroundColor: '#16110b',
  },
  meta: {
    gap: 4,
  },
  title: {
    color: '#f8fafc',
    fontSize: 14,
    fontWeight: '800',
  },
  detail: {
    color: '#c7d2e0',
    fontSize: 12,
    lineHeight: 18,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryAction: {
    borderRadius: 14,
    backgroundColor: '#fbbf24',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  reviewAction: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0b1627',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  reviewText: {
    color: '#e5eefb',
    fontWeight: '700',
  },
  primaryText: {
    color: '#1a1203',
    fontWeight: '800',
  },
  secondaryAction: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#6b4f13',
    backgroundColor: '#2d2310',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  secondaryText: {
    color: '#f8fafc',
    fontWeight: '700',
  },
  disabled: {
    opacity: 0.6,
  },
  empty: {
    color: '#94a3b8',
    fontSize: 13,
  },
});
