/**
 * MissionControlScreen — reimagined to match the Axon desktop dashboard.
 *
 * Desktop layout reference:
 *   Control Room header → Current Focus panel → Needs Attention strip
 *   → Mission Control HUD ring → Command Deck
 *   → Workspace Risk list → Priority Missions list
 *   → Timeline + Runtime collapsible rows
 *   → Quick Command bar → Local Tools grid
 *
 * This mobile version condenses those into a scrollable single-column
 * that preserves the Stark-Net / JARVIS glass aesthetic.
 */
import React, { useEffect, useMemo, useRef } from 'react';
import { Animated, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { SurfaceCard } from '@/components/SurfaceCard';
import { StatusPill } from '@/components/StatusPill';
import type { PlatformProjectCard, PlatformSnapshot } from '@/types/companion';

/* ── Colour constants (match desktop CSS variables) ────────────────── */
const C = {
  bg: '#020617',
  glass: 'rgba(15, 23, 42, 0.82)',
  glassLight: 'rgba(15, 23, 42, 0.55)',
  border: '#1e293b',
  cyan: '#22d3ee',
  cyanGlow: 'rgba(34, 211, 238, 0.15)',
  cyanBorder: 'rgba(34, 211, 238, 0.25)',
  orange: '#f97316',
  orangeGlow: 'rgba(249, 115, 22, 0.08)',
  text: '#f1f5f9',
  textSec: '#94a3b8',
  muted: '#64748b',
  dim: '#475569',
  emerald: '#34d399',
  amber: '#fbbf24',
  rose: '#fb7185',
} as const;

/* ── Helpers ───────────────────────────────────────────────────────── */
function postureColor(posture?: string) {
  if (!posture) return C.emerald;
  if (posture === 'urgent') return C.rose;
  if (posture === 'degraded') return C.amber;
  return C.emerald;
}

function postureLabel(posture?: string) {
  return String(posture || 'healthy').replace('_', ' ');
}

export function MissionControlScreen({
  snapshot,
  onOpenVoice,
  onOpenAttention,
  onOpenSessions,
  onOpenProjects,
  onOpenSettings,
  autoNavEnabled,
  onToggleAutoNav,
}: {
  snapshot: PlatformSnapshot | null;
  onOpenVoice?: () => void;
  onOpenAttention?: () => void;
  onOpenSessions?: () => void;
  onOpenProjects?: () => void;
  onOpenSettings?: () => void;
  autoNavEnabled?: boolean;
  onToggleAutoNav?: () => void;
}) {
  const { width } = useWindowDimensions();
  const posture = snapshot?.posture || 'healthy';
  const focusName = snapshot?.focus?.workspace?.name || 'Standing by';
  const focusDetail =
    snapshot?.focus?.workspace?.id
      ? 'The next visible action appears here as soon as Axon starts working.'
      : 'One place to see what Axon is doing, what needs attention, and which workspace needs you next.';
  const liveTitle = snapshot?.live?.operator?.title || 'Standing by';
  const liveDetail = snapshot?.live?.operator?.detail || 'Axon is holding position until the next command.';
  const liveActive = Boolean(snapshot?.live?.operator?.active);
  const attentionNow = Number(snapshot?.attention?.summary?.counts?.now || 0);
  const attentionWaiting = Number(snapshot?.attention?.summary?.counts?.waiting_on_me || 0);
  const runsCount = snapshot?.sessions?.length || 0;
  const systemsCount = snapshot?.systems?.length || snapshot?.mcp?.server_count || 0;
  const voiceArmed = Boolean(snapshot?.axon?.armed);
  const runtimeLabel = snapshot?.axon?.monitoring_state || 'Local';

  /* project health helper — derive from attention counts */
  const projectHealth = (p: PlatformProjectCard): number => {
    const counts = p.attention?.counts || {};
    const urgent = Number(counts.now || 0);
    const waiting = Number(counts.waiting_on_me || 0);
    if (urgent > 2) return 40;
    if (urgent > 0) return 60;
    if (waiting > 0) return 75;
    return 95;
  };
  const healthAvg = useMemo(() => {
    const projects = snapshot?.projects || [];
    if (!projects.length) return 0;
    return Math.round(projects.reduce((s, p) => s + projectHealth(p), 0) / projects.length);
  }, [snapshot?.projects]);

  /* weakest workspace */
  const weakest = useMemo(() => {
    const projects = snapshot?.projects || [];
    if (!projects.length) return null;
    const sorted = [...projects].sort((a, b) => projectHealth(a) - projectHealth(b));
    return sorted[0];
  }, [snapshot?.projects]);

  /* priority items from attention */
  const missions = useMemo(() => {
    const now = snapshot?.attention?.inbox?.now || snapshot?.attention?.summary?.top_now || [];
    return now.slice(0, 4);
  }, [snapshot?.attention]);

  /* top workspaces */
  const topProjects = useMemo(() => {
    const projects = snapshot?.projects || [];
    return [...projects]
      .sort((a, b) => projectHealth(a) - projectHealth(b))
      .slice(0, 4);
  }, [snapshot?.projects]);

  /* heartbeat pulse */
  const pulseAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1, duration: 1200, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 0, duration: 1200, useNativeDriver: true }),
      ]),
    ).start();
  }, [pulseAnim]);
  const pulseOpacity = pulseAnim.interpolate({ inputRange: [0, 1], outputRange: [0.4, 1] });

  return (
    <View style={styles.screen}>
      {/* ── Stark-Net header ──────────────────────────────── */}
      <View style={styles.headerRow}>
        <View style={styles.headerLeft}>
          <Animated.View
            style={[
              styles.heartbeat,
              { backgroundColor: liveActive ? C.emerald : C.dim, opacity: liveActive ? pulseOpacity : 0.4 },
            ]}
          />
          <Text style={styles.headerTitle}>Dashboard</Text>
          <View style={[styles.headerPill, { borderColor: C.cyanBorder, backgroundColor: C.cyanGlow }]}>
            <Text style={[styles.headerPillText, { color: C.cyan }]}>Control Room</Text>
          </View>
        </View>
        <View style={styles.headerRight}>
          <Pressable onPress={onOpenVoice} style={[styles.voiceChip, voiceArmed && styles.voiceChipActive]}>
            <Text style={styles.voiceChipIcon}>✦</Text>
            <Text style={[styles.voiceChipText, voiceArmed && { color: C.cyan }]}>Voice</Text>
          </Pressable>
          <View style={[styles.liveDot, { backgroundColor: liveActive ? C.emerald : C.dim }]} />
          <Text style={[styles.liveLabel, { color: liveActive ? C.emerald : C.muted }]}>
            {liveActive ? 'Live' : 'Idle'}
          </Text>
        </View>
      </View>

      {/* ── Status badges row ────────────────────────────── */}
      <View style={styles.badgeRow}>
        <StatusPill label={postureLabel(posture)} tone={posture === 'urgent' ? 'danger' : posture === 'degraded' ? 'warn' : 'ok'} />
        <StatusPill label={runtimeLabel} tone="accent" />
        <StatusPill label={voiceArmed ? 'Armed' : 'Standby'} tone={voiceArmed ? 'accent' : 'neutral'} />
      </View>

      {/* ── Current Focus panel (matches desktop) ────────── */}
      <SurfaceCard>
        <Text style={styles.eyebrow}>CURRENT FOCUS</Text>
        <View style={styles.focusRow}>
          <Animated.View
            style={[
              styles.focusDot,
              { backgroundColor: liveActive ? C.emerald : C.dim, opacity: liveActive ? pulseOpacity : 0.4 },
            ]}
          />
          <Text style={styles.focusTitle}>{liveTitle}</Text>
        </View>
        <Text style={styles.focusDetail}>{liveDetail}</Text>
      </SurfaceCard>

      {/* ── Needs Attention strip ─────────────────────────── */}
      {weakest && (
        <Pressable onPress={onOpenProjects}>
          <SurfaceCard>
            <View style={styles.attentionRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.eyebrow}>NEEDS ATTENTION</Text>
                <Text style={styles.attentionName}>{weakest.workspace?.name || 'Workspace'}</Text>
              </View>
              <View
                style={[
                  styles.healthBadge,
                  {
                    backgroundColor:
                      projectHealth(weakest) >= 70
                        ? 'rgba(52, 211, 153, 0.15)'
                        : projectHealth(weakest) >= 40
                        ? 'rgba(251, 191, 36, 0.15)'
                        : 'rgba(251, 113, 133, 0.15)',
                    borderColor:
                      projectHealth(weakest) >= 70
                        ? 'rgba(52, 211, 153, 0.3)'
                        : projectHealth(weakest) >= 40
                        ? 'rgba(251, 191, 36, 0.3)'
                        : 'rgba(251, 113, 133, 0.3)',
                  },
                ]}
              >
                <Text
                  style={[
                    styles.healthText,
                    {
                      color:
                        projectHealth(weakest) >= 70
                          ? C.emerald
                          : projectHealth(weakest) >= 40
                          ? C.amber
                          : C.rose,
                    },
                  ]}
                >
                  {projectHealth(weakest)}% health
                </Text>
              </View>
            </View>
          </SurfaceCard>
        </Pressable>
      )}

      {/* ── Metric cards row (matches desktop HUD grid) ──── */}
      <View style={styles.metricRow}>
        <View style={[styles.metricCard, { borderColor: C.cyanBorder }]}>
          <Text style={styles.metricLabel}>Attention</Text>
          <Text style={[styles.metricValue, { color: attentionNow > 0 ? C.rose : C.text }]}>
            {attentionNow}
          </Text>
          <Text style={styles.metricSub}>now</Text>
        </View>
        <View style={[styles.metricCard, { borderColor: C.cyanBorder }]}>
          <Text style={styles.metricLabel}>Waiting</Text>
          <Text style={[styles.metricValue, { color: attentionWaiting > 0 ? C.amber : C.text }]}>
            {attentionWaiting}
          </Text>
          <Text style={styles.metricSub}>on me</Text>
        </View>
        <View style={[styles.metricCard, { borderColor: C.cyanBorder }]}>
          <Text style={styles.metricLabel}>Runs</Text>
          <Text style={[styles.metricValue, { color: C.text }]}>{runsCount}</Text>
          <Text style={styles.metricSub}>active</Text>
        </View>
        <View style={[styles.metricCard, { borderColor: C.cyanBorder }]}>
          <Text style={styles.metricLabel}>Health</Text>
          <Text
            style={[
              styles.metricValue,
              { color: healthAvg >= 70 ? C.emerald : healthAvg >= 40 ? C.amber : C.rose },
            ]}
          >
            {healthAvg}%
          </Text>
          <Text style={styles.metricSub}>avg</Text>
        </View>
      </View>

      {/* ── Workspace Risk list ───────────────────────────── */}
      {topProjects.length > 0 && (
        <SurfaceCard>
          <View style={styles.sectionHeader}>
            <View>
              <Text style={styles.eyebrow}>WORKSPACE RISK</Text>
              <Text style={styles.sectionTitle}>Weakest workspaces first</Text>
            </View>
            <Pressable onPress={onOpenProjects} style={styles.sectionAction}>
              <Text style={styles.sectionActionText}>Open Workspaces</Text>
            </Pressable>
          </View>
          {topProjects.map((p, idx) => {
            const h = projectHealth(p);
            return (
            <View key={p.workspace?.id ?? idx} style={styles.projectRow}>
              <View
                style={[
                  styles.projectHealth,
                  {
                    backgroundColor:
                      h >= 70
                        ? 'rgba(52, 211, 153, 0.12)'
                        : h >= 40
                        ? 'rgba(251, 191, 36, 0.12)'
                        : 'rgba(251, 113, 133, 0.12)',
                  },
                ]}
              >
                <Text
                  style={[
                    styles.projectHealthText,
                    {
                      color:
                        h >= 70 ? C.emerald : h >= 40 ? C.amber : C.rose,
                    },
                  ]}
                >
                  {h}%
                </Text>
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.projectName} numberOfLines={1}>
                  {p.workspace?.name || 'Workspace'}
                </Text>
                <Text style={styles.projectStack} numberOfLines={1}>
                  {p.workspace?.git_branch || p.workspace?.status || 'unknown'}
                </Text>
              </View>
              <Text style={styles.chevron}>›</Text>
            </View>
            );
          })}
        </SurfaceCard>
      )}

      {/* ── Priority Missions ─────────────────────────────── */}
      {missions.length > 0 && (
        <SurfaceCard>
          <View style={styles.sectionHeader}>
            <View>
              <Text style={[styles.eyebrow, { color: C.amber }]}>PRIORITY MISSIONS</Text>
              <Text style={styles.sectionTitle}>What needs attention next</Text>
            </View>
            <View style={styles.countPill}>
              <Text style={styles.countPillText}>{missions.length} showing</Text>
            </View>
          </View>
          {missions.map((t: any) => (
            <Pressable key={t.id} onPress={onOpenAttention} style={[styles.missionRow, missionBorderStyle(t.severity)]}>
              <View
                style={[
                  styles.missionDot,
                  {
                    backgroundColor:
                      t.severity === 'critical' ? C.rose : t.severity === 'warning' ? C.amber : C.muted,
                  },
                ]}
              />
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.missionTitle} numberOfLines={2}>
                  {t.title}
                </Text>
                <View style={styles.missionMeta}>
                  <View style={styles.missionMetaPill}>
                    <Text style={styles.missionMetaText}>
                      {t.project_name || t.source || 'No workspace'}
                    </Text>
                  </View>
                  <View
                    style={[
                      styles.missionPriorityPill,
                      {
                        borderColor:
                          t.severity === 'critical'
                            ? 'rgba(251, 113, 133, 0.3)'
                            : t.severity === 'warning'
                            ? 'rgba(251, 191, 36, 0.3)'
                            : 'rgba(96, 165, 250, 0.3)',
                        backgroundColor:
                          t.severity === 'critical'
                            ? 'rgba(251, 113, 133, 0.12)'
                            : t.severity === 'warning'
                            ? 'rgba(251, 191, 36, 0.12)'
                            : 'rgba(96, 165, 250, 0.12)',
                      },
                    ]}
                  >
                    <Text
                      style={[
                        styles.missionPriorityText,
                        {
                          color:
                            t.severity === 'critical'
                              ? C.rose
                              : t.severity === 'warning'
                              ? C.amber
                              : '#60a5fa',
                        },
                      ]}
                    >
                      {t.severity || 'info'}
                    </Text>
                  </View>
                </View>
              </View>
            </Pressable>
          ))}
        </SurfaceCard>
      )}

      {/* ── Quick Actions (matches desktop Local Tools) ──── */}
      <SurfaceCard>
        <Text style={[styles.eyebrow, { color: C.amber }]}>QUICK ACTIONS</Text>
        <View style={styles.actionsGrid}>
          {[
            { label: 'Voice', icon: '✦', onPress: onOpenVoice },
            { label: 'Alerts', icon: '⚡', onPress: onOpenAttention },
            { label: 'Sessions', icon: '▶', onPress: onOpenSessions },
            { label: 'Projects', icon: '📂', onPress: onOpenProjects },
            { label: 'Settings', icon: '⚙', onPress: onOpenSettings },
            { label: 'Refresh', icon: '↻', onPress: onToggleAutoNav },
          ].map((action) => (
            <Pressable
              key={action.label}
              style={styles.actionButton}
              onPress={action.onPress}
            >
              <Text style={styles.actionIcon}>{action.icon}</Text>
              <Text style={styles.actionLabel}>{action.label}</Text>
            </Pressable>
          ))}
        </View>
      </SurfaceCard>

      {/* ── Runtime + Connection strip ────────────────────── */}
      <View style={styles.runtimeRow}>
        <View style={[styles.runtimeCard, { borderColor: C.border }]}>
          <Text style={[styles.eyebrowSmall, { color: C.dim }]}>RUNTIME</Text>
          <Text style={[styles.runtimeValue, { color: C.text }]}>{runtimeLabel}</Text>
        </View>
        <View style={[styles.runtimeCard, { borderColor: C.border }]}>
          <Text style={[styles.eyebrowSmall, { color: C.dim }]}>SYSTEMS</Text>
          <Text style={[styles.runtimeValue, { color: C.text }]}>{systemsCount} live</Text>
        </View>
      </View>
    </View>
  );
}

function missionBorderStyle(severity?: string) {
  if (severity === 'critical') return { borderColor: 'rgba(251, 113, 133, 0.25)', backgroundColor: 'rgba(251, 113, 133, 0.08)' };
  if (severity === 'warning') return { borderColor: 'rgba(251, 191, 36, 0.25)', backgroundColor: 'rgba(251, 191, 36, 0.06)' };
  return { borderColor: 'rgba(96, 165, 250, 0.25)', backgroundColor: 'rgba(96, 165, 250, 0.06)' };
}

/* ── Styles ─────────────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  screen: {
    gap: 14,
  },

  /* Header — matches desktop dashboard header */
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  heartbeat: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  headerTitle: {
    color: C.text,
    fontSize: 17,
    fontWeight: '700',
  },
  headerPill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  headerPillText: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  voiceChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
  },
  voiceChipActive: {
    borderColor: C.cyanBorder,
    backgroundColor: C.cyanGlow,
  },
  voiceChipIcon: {
    fontSize: 11,
    color: C.textSec,
  },
  voiceChipText: {
    fontSize: 10,
    fontWeight: '600',
    color: C.textSec,
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  liveLabel: {
    fontSize: 10,
    fontWeight: '600',
  },

  /* Badge row */
  badgeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },

  /* Eyebrow label — matches desktop `stark-dash-header` */
  eyebrow: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
    textTransform: 'uppercase',
    color: C.muted,
  },
  eyebrowSmall: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },

  /* Current Focus panel */
  focusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 6,
  },
  focusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  focusTitle: {
    color: C.text,
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
  },
  focusDetail: {
    color: C.textSec,
    fontSize: 12,
    lineHeight: 17,
  },

  /* Needs Attention */
  attentionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  attentionName: {
    color: C.text,
    fontSize: 14,
    fontWeight: '600',
    marginTop: 4,
  },
  healthBadge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  healthText: {
    fontSize: 10,
    fontWeight: '700',
  },

  /* Metric cards row */
  metricRow: {
    flexDirection: 'row',
    gap: 8,
  },
  metricCard: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 18,
    backgroundColor: C.glassLight,
    paddingVertical: 12,
    paddingHorizontal: 10,
    alignItems: 'center',
    gap: 2,
  },
  metricLabel: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    color: C.muted,
  },
  metricValue: {
    fontSize: 22,
    fontWeight: '800',
  },
  metricSub: {
    fontSize: 9,
    color: C.dim,
    fontWeight: '600',
  },

  /* Section headers */
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 8,
  },
  sectionTitle: {
    color: C.text,
    fontSize: 16,
    fontWeight: '700',
    marginTop: 4,
  },
  sectionAction: {
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
  },
  sectionActionText: {
    fontSize: 10,
    fontWeight: '600',
    color: C.textSec,
  },
  countPill: {
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
  },
  countPillText: {
    fontSize: 10,
    fontWeight: '600',
    color: C.textSec,
  },

  /* Project rows */
  projectRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(15, 23, 42, 0.45)',
  },
  projectHealth: {
    width: 44,
    height: 44,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  projectHealthText: {
    fontSize: 12,
    fontWeight: '800',
  },
  projectName: {
    color: C.text,
    fontSize: 13,
    fontWeight: '600',
  },
  projectStack: {
    color: C.muted,
    fontSize: 11,
    marginTop: 2,
  },
  chevron: {
    color: C.dim,
    fontSize: 18,
    fontWeight: '300',
  },

  /* Mission rows */
  missionRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 16,
    borderWidth: 1,
  },
  missionDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 5,
  },
  missionTitle: {
    color: C.text,
    fontSize: 13,
    fontWeight: '600',
    lineHeight: 18,
  },
  missionMeta: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    marginTop: 6,
  },
  missionMetaPill: {
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 999,
    paddingHorizontal: 6,
    paddingVertical: 2,
    backgroundColor: 'rgba(15, 23, 42, 0.7)',
  },
  missionMetaText: {
    fontSize: 10,
    fontWeight: '600',
    color: C.textSec,
  },
  missionPriorityPill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  missionPriorityText: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },

  /* Quick Actions grid */
  actionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 4,
  },
  actionButton: {
    width: '30%',
    flexGrow: 1,
    alignItems: 'center',
    gap: 4,
    paddingVertical: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
  },
  actionIcon: {
    fontSize: 16,
  },
  actionLabel: {
    fontSize: 10,
    fontWeight: '600',
    color: C.textSec,
  },

  /* Runtime row */
  runtimeRow: {
    flexDirection: 'row',
    gap: 8,
  },
  runtimeCard: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 16,
    backgroundColor: C.glassLight,
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 4,
  },
  runtimeValue: {
    fontSize: 13,
    fontWeight: '700',
  },
});
