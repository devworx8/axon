import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MetricCard } from '@/components/MetricCard';
import { StatusPill } from '@/components/StatusPill';
import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { ControlCapability, ExpoProjectStatus } from '@/types/companion';

type ExpoActionType =
  | 'expo.project.status'
  | 'expo.build.android.dev'
  | 'expo.build.ios.dev'
  | 'expo.build.list'
  | 'expo.update.publish';

type ExpoActionItem = {
  action_type: ExpoActionType;
  label: string;
  tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger';
  description: string;
};

const EXPO_ACTIONS: ExpoActionItem[] = [
  {
    action_type: 'expo.project.status',
    label: 'Project status',
    description: 'Refresh Expo project and credential state.',
    tone: 'accent',
  },
  {
    action_type: 'expo.build.android.dev',
    label: 'Android dev build',
    description: 'Queue a development build for Android.',
    tone: 'success',
  },
  {
    action_type: 'expo.build.ios.dev',
    label: 'iOS dev build',
    description: 'Queue a development build for iPhone.',
    tone: 'success',
  },
  {
    action_type: 'expo.build.list',
    label: 'Build list',
    description: 'Inspect recent Expo/EAS builds.',
    tone: 'neutral',
  },
  {
    action_type: 'expo.update.publish',
    label: 'Publish update',
    description: 'Ship a hot update to the current channel.',
    tone: 'warn',
  },
];

function capabilityAllows(capabilities: ControlCapability[] | undefined, actionType: ExpoActionType) {
  if (!capabilities?.length) return true;
  const capability = capabilities.find((item) => item.action_type === actionType);
  if (!capability) return false;
  return capability.available !== false;
}

function toneForStatus(status?: string): 'neutral' | 'accent' | 'success' | 'warn' | 'danger' {
  const value = String(status || '').toLowerCase();
  if (value.includes('fail') || value.includes('error') || value.includes('blocked')) return 'danger';
  if (value.includes('warn') || value.includes('pending')) return 'warn';
  if (value.includes('ready') || value.includes('success') || value.includes('healthy') || value.includes('running')) return 'success';
  if (value) return 'accent';
  return 'neutral';
}

function pillToneFromStatus(status?: string): 'neutral' | 'accent' | 'warn' | 'ok' | 'danger' {
  const tone = toneForStatus(status);
  if (tone === 'success') return 'ok';
  return tone;
}

function normalizeTime(value?: string) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function ExpoControlCard({
  expo,
  workspaceId,
  capabilities,
  busyActionType,
  onExecuteAction,
}: {
  expo?: ExpoProjectStatus | null;
  workspaceId?: number | null;
  capabilities?: ControlCapability[];
  busyActionType?: string | null;
  onExecuteAction: (actionType: ExpoActionType, payload?: Record<string, unknown>) => void;
}) {
  const hasProject = Boolean(expo?.project_id || expo?.project_name || expo?.slug);
  const buildCount = expo?.latest_builds?.length || expo?.latest_updates?.length || 0;
  const activeBuildCount = expo?.active_builds?.length || 0;
  const availableActions = EXPO_ACTIONS.filter((action) => capabilityAllows(capabilities, action.action_type));

  return (
    <SurfaceCard>
      <SurfaceHeader
        title="Expo / EAS"
        subtitle="Native builds, updates, and project health stay visible right in the command center."
      />
      <View style={styles.metrics}>
        <MetricCard label="Project" value={expo?.project_name || expo?.slug || 'Unlinked'} accent={hasProject ? 'accent' : 'neutral'} />
        <MetricCard label="Builds" value={buildCount} accent="success" />
        <MetricCard label="Active" value={activeBuildCount} accent={activeBuildCount ? 'warn' : 'neutral'} />
        <MetricCard label="Status" value={expo?.status || expo?.last_build_status || 'idle'} accent={toneForStatus(expo?.status || expo?.last_build_status) === 'danger' ? 'warn' : toneForStatus(expo?.status || expo?.last_build_status) === 'success' ? 'success' : 'accent'} />
      </View>
      <View style={styles.detailStack}>
        <Text style={styles.detailLine}>
          {expo?.owner || expo?.account_name || 'Expo account not yet linked'}
          {expo?.team_name ? ` · ${expo.team_name}` : ''}
        </Text>
        <Text style={styles.detailLine}>
          {expo?.branch ? `Branch ${expo.branch}` : 'Branch not reported yet'}
          {expo?.platform ? ` · ${expo.platform}` : ''}
          {expo?.build_profile ? ` · ${expo.build_profile}` : ''}
        </Text>
        <Text style={styles.detailLine}>
          {expo?.update_channel ? `Channel ${expo.update_channel}` : 'Channel not configured yet'}
          {expo?.runtime_version ? ` · Runtime ${expo.runtime_version}` : ' · Runtime not configured yet'}
        </Text>
        <Text style={styles.detailLine}>
          {expo?.last_build_at ? `Last build ${normalizeTime(expo.last_build_at)}` : 'No build timestamp yet'}
          {expo?.last_update_at ? ` · Last update ${normalizeTime(expo.last_update_at)}` : ''}
        </Text>
      </View>
      <View style={styles.pills}>
        {expo?.status ? <StatusPill label={expo.status} tone={pillToneFromStatus(expo.status)} /> : null}
        {expo?.update_channel ? <StatusPill label={expo.update_channel} tone="accent" /> : null}
        {expo?.runtime_version ? <StatusPill label={expo.runtime_version} tone="accent" /> : null}
        {expo?.runtime ? <StatusPill label={expo.runtime} tone="neutral" /> : null}
      </View>
      <View style={styles.actions}>
        {availableActions.map((action) => {
          const busy = busyActionType === action.action_type;
          return (
            <Pressable
              key={action.action_type}
              onPress={() => onExecuteAction(action.action_type, { workspace_id: workspaceId })}
              disabled={busy || !hasProject}
              style={[
                styles.action,
                busy || !hasProject ? styles.actionDisabled : null,
                action.tone === 'warn' ? styles.actionWarn : null,
              ]}
            >
              <Text style={styles.actionTitle}>{busy ? 'Working…' : action.label}</Text>
              <Text style={styles.actionBody}>{action.description}</Text>
            </Pressable>
          );
        })}
      </View>
      <View style={styles.buildStack}>
        {(expo?.active_builds?.length ? expo.active_builds : (expo?.latest_builds || expo?.latest_updates || [])).slice(0, 3).map((item, index) => (
          <View key={String(item.id || item.name || index)} style={styles.buildRow}>
            <View style={styles.buildMeta}>
              <Text style={styles.buildTitle}>{item.name || item.platform || 'Build'}</Text>
              <Text style={styles.detailLine}>
                {item.status || 'unknown'}
                {item.branch ? ` · ${item.branch}` : ''}
                {item.meta?.channel ? ` · ${String(item.meta.channel)}` : ''}
                {item.message ? ` · ${item.message}` : ''}
              </Text>
            </View>
            <View style={styles.buildPills}>
              {item.platform ? <StatusPill label={item.platform} tone="neutral" /> : null}
              {item.runtime_version ? <StatusPill label={item.runtime_version} tone="accent" /> : null}
            </View>
          </View>
        ))}
      </View>
      {!hasProject ? <Text style={styles.empty}>Expo project fields will appear here once the backend starts sending them.</Text> : null}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  metrics: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  detailStack: {
    gap: 4,
  },
  detailLine: {
    color: '#94a3b8',
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
  action: {
    minWidth: 150,
    flexGrow: 1,
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    gap: 4,
    backgroundColor: '#0b1627',
  },
  actionWarn: {
    borderColor: '#5f3f14',
    backgroundColor: '#16110b',
  },
  actionDisabled: {
    opacity: 0.6,
  },
  actionTitle: {
    color: '#e5eefb',
    fontSize: 13,
    fontWeight: '800',
  },
  actionBody: {
    color: '#94a3b8',
    fontSize: 12,
    lineHeight: 17,
  },
  buildStack: {
    gap: 8,
  },
  buildRow: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 14,
    padding: 12,
    gap: 8,
    backgroundColor: '#0b1627',
  },
  buildMeta: {
    gap: 4,
  },
  buildTitle: {
    color: '#e5eefb',
    fontSize: 13,
    fontWeight: '800',
  },
  buildPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  empty: {
    color: '#7f93ad',
    fontSize: 13,
  },
});
