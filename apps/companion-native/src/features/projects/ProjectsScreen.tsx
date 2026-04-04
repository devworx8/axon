import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { ExpoControlCard } from '@/features/expo/ExpoControlCard';
import { ExpoProjectStatus, PlatformProjectCard } from '@/types/companion';

export function ProjectsScreen({
  projects,
  activeWorkspaceId,
  expoProject,
  expoBusyActionType,
  onFocusWorkspace,
  onInspectWorkspace,
  onRestartPreview,
  onStopPreview,
  onDeploy,
  onRollback,
  onExpoProjectStatus,
  onExpoBuildAndroidDev,
  onExpoBuildIosDev,
  onExpoBuildList,
  onExpoPublishUpdate,
}: {
  projects: PlatformProjectCard[];
  activeWorkspaceId?: number | null;
  expoProject?: ExpoProjectStatus | null;
  expoBusyActionType?: string | null;
  onFocusWorkspace?: (workspaceId: number | null) => void;
  onInspectWorkspace?: (workspaceId: number | null) => void;
  onRestartPreview?: (workspaceId: number | null) => void;
  onStopPreview?: (workspaceId: number | null) => void;
  onDeploy?: (workspaceId: number | null) => void;
  onRollback?: (workspaceId: number | null) => void;
  onExpoProjectStatus?: (workspaceId: number | null) => void;
  onExpoBuildAndroidDev?: (workspaceId: number | null) => void;
  onExpoBuildIosDev?: (workspaceId: number | null) => void;
  onExpoBuildList?: (workspaceId: number | null) => void;
  onExpoPublishUpdate?: (workspaceId: number | null) => void;
}) {
  const linkedCount = projects.filter((item) => (item.relationships || []).length > 0).length;

  return (
    <SurfaceCard>
      <SurfaceHeader title="Projects" subtitle="Select focus, inspect status, and keep linked systems visible per workspace." />
      <View style={styles.metrics}>
        <MetricCard label="Projects" value={projects.length} accent="accent" />
        <MetricCard label="Linked" value={linkedCount} accent="success" />
      </View>
      <ExpoControlCard
        expo={expoProject}
        workspaceId={activeWorkspaceId}
        busyActionType={expoBusyActionType}
        onExecuteAction={(actionType, payload) => {
          const workspaceId = typeof payload?.workspace_id === 'number' ? payload.workspace_id : activeWorkspaceId ?? null;
          if (actionType === 'expo.project.status') {
            onExpoProjectStatus?.(workspaceId);
            return;
          }
          if (actionType === 'expo.build.android.dev') {
            onExpoBuildAndroidDev?.(workspaceId);
            return;
          }
          if (actionType === 'expo.build.ios.dev') {
            onExpoBuildIosDev?.(workspaceId);
            return;
          }
          if (actionType === 'expo.build.list') {
            onExpoBuildList?.(workspaceId);
            return;
          }
          if (actionType === 'expo.update.publish') {
            onExpoPublishUpdate?.(workspaceId);
          }
        }}
      />
      <View style={styles.stack}>
        {projects.map((project) => {
          const workspaceId = project.workspace?.id ?? null;
          const active = workspaceId === activeWorkspaceId;
          const hasVercel = (project.relationships || []).some((relationship) => String(relationship.external_system || '').trim().toLowerCase() === 'vercel');
          const hasExpo = Boolean(project.expo?.project_id || project.expo?.project_name || project.expo?.slug || (project.expo?.available_actions || []).length);
          return (
            <View key={String(workspaceId || project.workspace?.name || Math.random())} style={[styles.card, active ? styles.cardActive : null]}>
              <View style={styles.headerRow}>
                <View style={styles.meta}>
                  <Text style={styles.title}>{project.workspace?.name || 'Workspace'}</Text>
                  <Text style={styles.path}>{project.workspace?.path || 'No local path recorded'}</Text>
                </View>
                <View style={styles.pills}>
                  {active ? <StatusPill label="Focused" tone="ok" /> : null}
                  {project.workspace?.git_branch ? <StatusPill label={project.workspace.git_branch} tone="accent" /> : null}
                </View>
              </View>
              <Text style={styles.metaLine}>
                {(project.relationships || []).length} linked systems · now {project.attention?.counts?.now || 0} · waiting {project.attention?.counts?.waiting_on_me || 0}
              </Text>
              {project.preview?.status ? (
                <Text style={styles.metaLine}>
                  Preview {String(project.preview.status).replace('_', ' ')}
                  {project.preview?.url ? ` · ${String(project.preview.url)}` : ''}
                </Text>
              ) : null}
              {hasExpo ? (
                <View style={styles.expoBlock}>
                  <Text style={styles.expoTitle}>Expo / EAS</Text>
                  <Text style={styles.metaLine}>
                    {project.expo?.project_name || project.expo?.slug || 'Project linked'}
                    {project.expo?.status ? ` · ${project.expo.status}` : ''}
                    {project.expo?.build_profile ? ` · ${project.expo.build_profile}` : ''}
                  </Text>
                  <View style={styles.expoButtons}>
                    <Pressable onPress={() => onExpoProjectStatus?.(workspaceId)} style={styles.expoButton}>
                      <Text style={styles.expoButtonText}>Status</Text>
                    </Pressable>
                    <Pressable onPress={() => onExpoBuildAndroidDev?.(workspaceId)} style={styles.expoButton}>
                      <Text style={styles.expoButtonText}>Android dev</Text>
                    </Pressable>
                    <Pressable onPress={() => onExpoBuildIosDev?.(workspaceId)} style={styles.expoButton}>
                      <Text style={styles.expoButtonText}>iOS dev</Text>
                    </Pressable>
                    <Pressable onPress={() => onExpoBuildList?.(workspaceId)} style={styles.expoButton}>
                      <Text style={styles.expoButtonText}>Builds</Text>
                    </Pressable>
                    <Pressable onPress={() => onExpoPublishUpdate?.(workspaceId)} style={styles.expoButton}>
                      <Text style={styles.expoButtonText}>Update</Text>
                    </Pressable>
                  </View>
                </View>
              ) : null}
              <View style={styles.actions}>
                <Pressable onPress={() => onFocusWorkspace?.(workspaceId)} style={styles.primaryAction}>
                  <Text style={styles.primaryActionText}>{active ? 'Focused' : 'Focus project'}</Text>
                </Pressable>
                <Pressable onPress={() => onInspectWorkspace?.(workspaceId)} style={styles.secondaryAction}>
                  <Text style={styles.secondaryActionText}>Inspect</Text>
                </Pressable>
                <Pressable onPress={() => onRestartPreview?.(workspaceId)} style={styles.secondaryAction}>
                  <Text style={styles.secondaryActionText}>Restart preview</Text>
                </Pressable>
                {project.preview?.running ? (
                  <Pressable onPress={() => onStopPreview?.(workspaceId)} style={styles.secondaryAction}>
                    <Text style={styles.secondaryActionText}>Stop preview</Text>
                  </Pressable>
                ) : null}
                {hasVercel ? (
                  <Pressable onPress={() => onDeploy?.(workspaceId)} style={styles.secondaryAction}>
                    <Text style={styles.secondaryActionText}>Deploy</Text>
                  </Pressable>
                ) : null}
                {hasVercel ? (
                  <Pressable onPress={() => onRollback?.(workspaceId)} style={styles.secondaryAction}>
                    <Text style={styles.secondaryActionText}>Rollback</Text>
                  </Pressable>
                ) : null}
              </View>
              <View style={styles.relationships}>
                {(project.relationships || []).slice(0, 4).map((relationship) => (
                  <StatusPill
                    key={`${relationship.external_system}-${relationship.external_id || relationship.external_name}`}
                    label={`${relationship.external_system}${relationship.external_name ? ` · ${relationship.external_name}` : ''}`}
                    tone="neutral"
                  />
                ))}
              </View>
            </View>
          );
        })}
      </View>
    </SurfaceCard>
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
  card: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 10,
    backgroundColor: '#0b1627',
  },
  cardActive: {
    borderColor: '#38bdf8',
    backgroundColor: '#0d1b2f',
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  meta: {
    flex: 1,
    gap: 4,
  },
  title: {
    color: '#e5eefb',
    fontSize: 15,
    fontWeight: '800',
  },
  path: {
    color: '#7f93ad',
    fontSize: 12,
    lineHeight: 18,
  },
  pills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    gap: 6,
  },
  metaLine: {
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 18,
  },
  expoBlock: {
    borderWidth: 1,
    borderColor: '#1e3a8a',
    borderRadius: 14,
    padding: 12,
    gap: 8,
    backgroundColor: '#0a1220',
  },
  expoTitle: {
    color: '#dbeafe',
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 0.7,
    textTransform: 'uppercase',
  },
  expoButtons: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  expoButton: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#1d4ed8',
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#0f172a',
  },
  expoButtonText: {
    color: '#dbeafe',
    fontSize: 11,
    fontWeight: '700',
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  primaryAction: {
    borderRadius: 14,
    backgroundColor: '#38bdf8',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  primaryActionText: {
    color: '#08111f',
    fontWeight: '800',
  },
  secondaryAction: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0f172a',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  secondaryActionText: {
    color: '#e5eefb',
    fontWeight: '700',
  },
  relationships: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
});
