import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { WorkspaceSummary } from '@/types/companion';

export function WorkspaceScreen({
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
}: {
  workspaces: WorkspaceSummary[];
  activeWorkspaceId?: number | null;
  onSelectWorkspace?: (workspaceId: number | null) => void;
}) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Workspaces" subtitle="Choose the project Axon should treat as your mobile focus." />
      <View style={styles.metrics}>
        <MetricCard label="Tracked" value={workspaces.length} accent="accent" />
        <MetricCard
          label="Linked"
          value={workspaces.filter((workspace) => (workspace.relationships || []).length > 0).length}
          accent="success"
        />
      </View>
      <View style={styles.stack}>
        {workspaces.length ? workspaces.map((workspace, index) => (
          <Pressable
            key={index}
            style={[styles.row, workspaceId(workspace) === activeWorkspaceId ? styles.rowActive : null]}
            onPress={() => onSelectWorkspace?.(workspaceId(workspace))}
          >
            <Text style={styles.title}>{workspaceName(workspace, index)}</Text>
            <Text style={styles.detail}>{workspacePath(workspace)}</Text>
            <View style={styles.metaRow}>
              <Text style={styles.metaText}>
                {(workspace.relationships || []).length} linked systems
              </Text>
              <Text style={styles.metaText}>
                {(workspace.attention as { counts?: { now?: number } } | undefined)?.counts?.now || 0} urgent
              </Text>
            </View>
            <View style={styles.metaRow}>
              {workspaceId(workspace) === activeWorkspaceId ? <StatusPill label="Active workspace" tone="ok" /> : null}
              {onSelectWorkspace ? (
                <StatusPill
                  label={workspaceId(workspace) === activeWorkspaceId ? 'Selected' : 'Tap to focus'}
                  tone={workspaceId(workspace) === activeWorkspaceId ? 'accent' : 'neutral'}
                />
              ) : null}
            </View>
            <View style={styles.pills}>
              {(workspace.relationships || []).slice(0, 4).map((relationship) => (
                <View key={`${relationship.external_system}-${relationship.external_id || relationship.external_name}`} style={styles.pill}>
                  <Text style={styles.pillText}>
                    {relationship.external_system}
                    {relationship.external_name ? ` · ${relationship.external_name}` : ''}
                  </Text>
                </View>
              ))}
            </View>
          </Pressable>
        )) : <Text style={styles.empty}>No linked workspaces yet.</Text>}
      </View>
    </SurfaceCard>
  );
}

function workspaceName(workspace: WorkspaceSummary, index: number) {
  const info = workspace.workspace as { name?: string } | undefined;
  return info?.name || `Workspace ${index + 1}`;
}

function workspacePath(workspace: WorkspaceSummary) {
  const info = workspace.workspace as { path?: string } | undefined;
  return info?.path || 'No local path recorded yet.';
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
  row: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 14,
    padding: 12,
    gap: 4,
  },
  rowActive: {
    borderColor: '#38bdf8',
    backgroundColor: '#0d1b2f',
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
  metaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  metaText: {
    color: '#94a3b8',
    fontSize: 11,
    fontWeight: '600',
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
    color: '#cfe0f7',
    fontSize: 11,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});

function workspaceId(workspace: WorkspaceSummary) {
  const info = workspace.workspace as { id?: number | null } | undefined;
  return info?.id ?? null;
}
