import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { WorkspaceSummary } from '@/types/companion';

export function WorkspaceScreen({ workspaces }: { workspaces: WorkspaceSummary[] }) {
  return (
    <SurfaceCard>
      <SurfaceHeader title="Workspaces" subtitle="The projects Axon knows about and should keep current." />
      <View style={styles.stack}>
        {workspaces.length ? workspaces.map((workspace, index) => (
          <View key={index} style={styles.row}>
            <Text style={styles.title}>Workspace {index + 1}</Text>
            <Text style={styles.detail}>Linked systems and live attention will render here.</Text>
          </View>
        )) : <Text style={styles.empty}>No linked workspaces yet.</Text>}
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
    borderRadius: 14,
    padding: 12,
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
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});

