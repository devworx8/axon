import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { ActionReceipt } from '@/types/companion';

export function ReceiptListCard({
  receipts,
}: {
  receipts: ActionReceipt[];
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Action receipts" subtitle="Every typed action leaves an audit trail so you can see what happened from mobile." />
      <View style={styles.stack}>
        {receipts.length ? receipts.map((receipt) => (
          <View key={receipt.id} style={styles.row}>
            <View style={styles.meta}>
              <Text style={styles.title}>{receipt.title || receipt.action_type}</Text>
              <Text style={styles.detail}>{receipt.summary || receipt.outcome || 'No summary recorded.'}</Text>
            </View>
            <View style={styles.pills}>
              {receipt.status ? <StatusPill label={receipt.status} tone={receipt.status === 'completed' ? 'ok' : receipt.status === 'challenge_required' ? 'warn' : 'neutral'} /> : null}
              {receipt.risk_tier ? <StatusPill label={String(receipt.risk_tier)} tone={receipt.risk_tier === 'destructive' ? 'danger' : 'neutral'} /> : null}
            </View>
          </View>
        )) : <Text style={styles.empty}>No action receipts yet.</Text>}
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
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 8,
    backgroundColor: '#0b1627',
  },
  meta: {
    gap: 4,
  },
  title: {
    color: '#e5eefb',
    fontSize: 14,
    fontWeight: '800',
  },
  detail: {
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 18,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});
