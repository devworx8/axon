import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
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
  inbox,
  onResolve,
  onSync,
  syncing,
}: {
  summary: { counts: Record<string, number> };
  inbox: { now: AttentionItem[]; waiting_on_me: AttentionItem[]; watch: AttentionItem[] };
  onResolve?: (id: number) => void;
  onSync?: () => void;
  syncing?: boolean;
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Attention" subtitle="Now, waiting on me, and watch." />
      {onSync ? (
        <Pressable onPress={onSync} disabled={syncing} style={[styles.syncAction, syncing ? styles.syncActionDisabled : null]}>
          <Text style={styles.syncActionText}>{syncing ? 'Syncing…' : 'Sync connector signals'}</Text>
        </Pressable>
      ) : null}
      <View style={styles.metrics}>
        <MetricCard label="Now" value={summary.counts.now || 0} accent="warn" />
        <MetricCard label="Waiting" value={summary.counts.waiting_on_me || 0} accent="accent" />
        <MetricCard label="Watch" value={summary.counts.watch || 0} />
      </View>
      <View style={styles.stack}>
        <AttentionBucket title="Now" items={inbox.now} onResolve={onResolve} />
        <AttentionBucket title="Waiting on me" items={inbox.waiting_on_me} onResolve={onResolve} />
        <AttentionBucket title="Watch" items={inbox.watch} onResolve={onResolve} />
      </View>
    </SurfaceCard>
  );
}

function AttentionBucket({
  title,
  items,
  onResolve,
}: {
  title: string;
  items: AttentionItem[];
  onResolve?: (id: number) => void;
}) {
  return (
    <View style={styles.bucket}>
      <Text style={styles.bucketTitle}>{title}</Text>
      <View style={styles.stack}>
        {items.length ? items.map(item => <AttentionRow key={item.id} item={item} onResolve={onResolve} />) : <Text style={styles.empty}>Quiet for now.</Text>}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  stack: {
    gap: 10,
  },
  bucket: {
    gap: 10,
  },
  bucketTitle: {
    color: '#e5eefb',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
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
  syncAction: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  syncActionDisabled: {
    opacity: 0.6,
  },
  syncActionText: {
    color: '#08111f',
    fontSize: 12,
    fontWeight: '800',
  },
});
