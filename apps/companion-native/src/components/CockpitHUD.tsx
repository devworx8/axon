import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

type ConnectionState = 'live' | 'polling' | 'offline';
type VoiceState = 'ready' | 'listening' | 'processing' | 'unavailable';

export function CockpitHUD({
  connectionState = 'polling',
  voiceState = 'ready',
  activeSessions = 0,
  pendingApprovals = 0,
}: {
  connectionState?: ConnectionState;
  voiceState?: VoiceState;
  activeSessions?: number;
  pendingApprovals?: number;
}) {
  const connColor = CONNECTION_COLORS[connectionState];
  const connLabel = CONNECTION_LABELS[connectionState];
  const voiceColor = VOICE_COLORS[voiceState];

  return (
    <View style={styles.bar} accessibilityRole="toolbar" accessibilityLabel="Cockpit status">
      {/* Connection indicator */}
      <View style={styles.segment}>
        <View style={[styles.dot, { backgroundColor: connColor }]} />
        <Text style={styles.label}>{connLabel}</Text>
      </View>

      {/* Voice indicator */}
      <View style={styles.segment}>
        <Text style={[styles.icon, { color: voiceColor }]}>{'mic'}</Text>
      </View>

      {/* Active sessions */}
      {activeSessions > 0 && (
        <View style={styles.segment}>
          <Text style={styles.badge}>{activeSessions}</Text>
          <Text style={styles.label}>active</Text>
        </View>
      )}

      {/* Pending approvals */}
      {pendingApprovals > 0 && (
        <View style={styles.segment}>
          <View style={styles.alertBadge}>
            <Text style={styles.alertBadgeText}>{pendingApprovals}</Text>
          </View>
          <Text style={[styles.label, { color: '#ef4444' }]}>pending</Text>
        </View>
      )}
    </View>
  );
}

const CONNECTION_COLORS: Record<ConnectionState, string> = {
  live: '#22c55e',
  polling: '#f59e0b',
  offline: '#ef4444',
};

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  live: 'Live',
  polling: 'Polling',
  offline: 'Offline',
};

const VOICE_COLORS: Record<VoiceState, string> = {
  ready: '#38bdf8',
  listening: '#22c55e',
  processing: '#f59e0b',
  unavailable: '#64748b',
};

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 6,
    gap: 16,
    backgroundColor: 'rgba(10, 14, 23, 0.9)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(56, 189, 248, 0.1)',
  },
  segment: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  label: {
    fontSize: 11,
    fontWeight: '600',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  icon: {
    fontSize: 14,
    fontWeight: '700',
  },
  badge: {
    fontSize: 13,
    fontWeight: '800',
    color: '#38bdf8',
  },
  alertBadge: {
    backgroundColor: '#ef4444',
    borderRadius: 8,
    minWidth: 16,
    height: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  alertBadgeText: {
    fontSize: 10,
    fontWeight: '800',
    color: '#ffffff',
  },
});
