import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import { AttentionItem } from '@/types/companion';

function AttentionRow({ item, onResolve }: { item: AttentionItem; onResolve?: (id: number) => void }) {
  return (
    <View style={styles.row}>
      <View style={styles.meta}>
        <Text style={styles.title}>{item.title || 'Attention item'}</Text>
        <Text style={styles.detail}>{item.summary || item.detail || item.source || 'Needs review'}</Text>
      </View>
      <View style={styles.rowActions}>
        <StatusPill label={item.severity || 'medium'} tone={item.severity === 'high' || item.severity === 'critical' ? 'danger' : 'neutral'} />
        {onResolve ? (
          <Pressable onPress={() => onResolve(item.id)} style={styles.action}>
            <Text style={styles.actionText}>Resolve</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

export function AttentionScreen({
  summary,
  items,
  onResolve,
}: {
  summary: { counts: Record<string, number> };
  items: AttentionItem[];
  onResolve?: (id: number) => void;
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Attention" subtitle="Now, waiting on me, and watch." />
      <Text style={styles.counts}>Now {summary.counts.now || 0} · Waiting {summary.counts.waiting_on_me || 0} · Watch {summary.counts.watch || 0}</Text>
      <View style={styles.stack}>
        {items.length ? items.map(item => <AttentionRow key={item.id} item={item} onResolve={onResolve} />) : <Text style={styles.empty}>No attention items yet.</Text>}
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  counts: {
    color: '#7f93ad',
    fontSize: 12,
  },
  stack: {
    gap: 10,
  },
  row: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 14,
    padding: 12,
    gap: 12,
  },
  meta: {
    gap: 4,
  },
  title: {
    color: '#e5eefb',
    fontSize: 14,
    fontWeight: '700',
  },
  detail: {
    color: '#7f93ad',
    fontSize: 12,
    lineHeight: 17,
  },
  rowActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    justifyContent: 'space-between',
  },
  action: {
    borderRadius: 12,
    backgroundColor: '#1e293b',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  actionText: {
    color: '#e5eefb',
    fontSize: 12,
    fontWeight: '700',
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});

