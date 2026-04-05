import React, { useEffect, useMemo, useRef } from 'react';
import { Animated, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { PlatformSnapshot } from '@/types/companion';

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
  const { width, height } = useWindowDimensions();
  const padding = Math.min(10, Math.max(6, width * 0.03));
  const maxWidth = Math.max(300, Math.min(width - padding * 2, 520));
  const ringSize = Math.max(200, Math.min(width * 0.9, height * 0.58));
  const ringInner = ringSize * 0.72;
  const ringMid = ringSize * 0.48;
  const coreSize = ringSize * 0.2;
  const opsStatus = String(snapshot?.posture || 'healthy').replace('_', ' ');
  const attentionNow = Number(snapshot?.attention?.summary?.counts?.now || 0);
  const runsCount = snapshot?.sessions?.length || 0;
  const systemsCount = snapshot?.systems?.length || snapshot?.mcp?.server_count || 0;
  const voiceStatus = snapshot?.axon?.armed
    ? (snapshot?.axon?.monitoring_state === 'engaged'
        ? 'engaged'
        : snapshot?.axon?.monitoring_state === 'degraded'
          ? 'degraded'
          : 'armed')
    : (snapshot?.axon?.status || 'standby');
  const focusName = snapshot?.focus?.workspace?.name || 'Global platform view';
  const cpuValue = snapshot?.systems?.find((item) => String(item.key || item.label || '').toLowerCase().includes('cpu'))?.meta?.value;
  const memValue = snapshot?.systems?.find((item) => String(item.key || item.label || '').toLowerCase().includes('mem'))?.meta?.value;
  const cpuDisplay = typeof cpuValue === 'number' ? `${cpuValue}%` : '53%';
  const memDisplay = typeof memValue === 'number' ? `${memValue}%` : '80%';
  const systemLabels = useMemo(() => {
    if (snapshot?.systems?.length) {
      return snapshot.systems
        .slice(0, 5)
        .map((item) => item.label || item.key || 'System');
    }
    return ['GitHub', 'Vercel', 'Sentry', 'Expo / EAS', 'Axon runtime'];
  }, [snapshot?.systems]);

  const sweepAnim = useRef(new Animated.Value(0)).current;
  const ringPulse = useRef(new Animated.Value(0)).current;
  const floatAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.timing(sweepAnim, {
        toValue: 1,
        duration: 7000,
        useNativeDriver: true,
      }),
    ).start();
    Animated.loop(
      Animated.sequence([
        Animated.timing(ringPulse, { toValue: 1, duration: 2600, useNativeDriver: true }),
        Animated.timing(ringPulse, { toValue: 0, duration: 2600, useNativeDriver: true }),
      ]),
    ).start();
    Animated.loop(
      Animated.sequence([
        Animated.timing(floatAnim, { toValue: 1, duration: 2400, useNativeDriver: true }),
        Animated.timing(floatAnim, { toValue: 0, duration: 2400, useNativeDriver: true }),
      ]),
    ).start();
  }, [floatAnim, ringPulse, sweepAnim]);

  const sweepTranslate = sweepAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [-ringSize * 0.4, ringSize * 0.4],
  });
  const pulseScale = ringPulse.interpolate({
    inputRange: [0, 1],
    outputRange: [1, 1.04],
  });
  const floatOffset = floatAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0, -6],
  });

  const statusChips = [
    { label: 'Ops', value: opsStatus },
    { label: 'Voice', value: voiceStatus },
    { label: 'Attention', value: `${attentionNow} now` },
    { label: 'Systems', value: `${systemsCount} live` },
    { label: 'Runs', value: `${runsCount} active` },
  ];

  return (
    <View style={[styles.screen, { paddingHorizontal: padding, paddingTop: padding, paddingBottom: padding }]}>
      <View style={styles.hudBackdrop} />
      <View style={[styles.hudGlow, { width: ringSize * 1.6, height: ringSize * 1.6, borderRadius: ringSize * 0.8 }]} />
      <View style={[styles.hudGlowSecondary, { width: ringSize * 1.2, height: ringSize * 1.2, borderRadius: ringSize * 0.6 }]} />
      <View style={[styles.hudDot, styles.hudDotA]} />
      <View style={[styles.hudDot, styles.hudDotB]} />
      <View style={[styles.hudDot, styles.hudDotC]} />
      <View style={styles.scanline} />
      <View style={[styles.stack, { maxWidth, minHeight: height - padding * 2 }]}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.hudTitle}>Axon Command Center</Text>
            <Text style={styles.hudSubtitle}>Cinematic ops cockpit. Live wiring comes next.</Text>
          </View>
          <Pressable
            style={[styles.autoChip, autoNavEnabled ? styles.autoChipActive : null]}
            onPress={onToggleAutoNav}
          >
            <Text style={styles.autoChipLabel}>{autoNavEnabled ? 'AUTO' : 'MANUAL'}</Text>
          </Pressable>
        </View>

        <View style={styles.statusRow}>
          {statusChips.map((chip) => (
            <View key={chip.label} style={styles.statusChip}>
              <View style={styles.statusDot} />
              <View>
                <Text style={styles.statusLabel}>{chip.label}</Text>
                <Text style={styles.statusValue}>{chip.value}</Text>
              </View>
            </View>
          ))}
        </View>

        <View style={styles.heroWrap}>
          <View style={[styles.hero, { width: ringSize, height: ringSize }]}>
            <View style={[styles.heroGlow, { width: ringSize + 120, height: ringSize + 120, borderRadius: (ringSize + 120) / 2 }]} />
            <Animated.View style={[styles.heroHalo, { transform: [{ scale: pulseScale }] }]} />
            <View style={styles.heroArcLeft} />
            <View style={styles.heroArcRight} />
            <Animated.View style={[styles.heroRingOuter, { width: ringSize, height: ringSize, borderRadius: ringSize / 2, transform: [{ scale: pulseScale }] }]}>
              <View style={[styles.heroRingTicks, { width: ringSize * 0.86, height: ringSize * 0.86, borderRadius: ringSize * 0.43 }]} />
              <View style={[styles.heroRingMid, { width: ringInner, height: ringInner, borderRadius: ringInner / 2 }]}>
                <View style={[styles.heroRingInner, { width: ringMid, height: ringMid, borderRadius: ringMid / 2 }]}>
                  <View style={[styles.heroCore, { width: coreSize, height: coreSize, borderRadius: coreSize / 2 }]} />
                </View>
              </View>
            </Animated.View>
            <Animated.View style={[styles.heroSweep, { transform: [{ translateX: sweepTranslate }, { rotate: '20deg' }] }]} />
            <Text style={styles.heroTitle}>A.X.O.N</Text>
            <Text style={styles.heroSub}>Voice ready · Command center online</Text>
          </View>
        </View>

        <View style={styles.bottomRow}>
          <Animated.View style={[styles.floatingCard, { transform: [{ translateY: floatOffset }] }]}>
            <View style={styles.statCard}>
              <Text style={styles.statLabel}>CPU</Text>
              <Text style={styles.statValue}>{cpuDisplay}</Text>
              <View style={styles.miniRing} />
            </View>
          </Animated.View>
          <Animated.View style={[styles.floatingCard, { transform: [{ translateY: floatOffset }] }]}>
            <View style={styles.statCard}>
              <Text style={styles.statLabel}>Memory</Text>
              <Text style={styles.statValue}>{memDisplay}</Text>
              <View style={styles.miniRing} />
            </View>
          </Animated.View>
        </View>

        <Animated.View style={[styles.floatingCard, { transform: [{ translateY: floatOffset }] }]}>
          <View style={styles.focusPanel}>
            <Text style={styles.panelTitle}>Systems + Focus</Text>
            <View style={styles.systemStrip}>
              {systemLabels.map((item) => (
                <View key={String(item)} style={styles.systemNode}>
                  <View style={styles.systemDot} />
                  <Text style={styles.systemLabel}>{String(item)}</Text>
                </View>
              ))}
            </View>
            <Text style={styles.focusTitle}>{focusName}</Text>
            <Text style={styles.focusSub}>
              {snapshot?.axon?.armed ? 'Voice loop armed.' : 'Voice loop ready.'} Awaiting command.
            </Text>
          </View>
        </Animated.View>

        <View style={styles.hudActionsRow}>
          {[
            { label: 'Voice', onPress: onOpenVoice },
            { label: 'Alert', onPress: onOpenAttention },
            { label: 'Runs', onPress: onOpenSessions },
            { label: 'Settings', onPress: onOpenSettings },
          ].map((item) => (
            <Pressable key={item.label} style={styles.hudActionButton} onPress={item.onPress}>
              <Text style={styles.hudActionText}>{item.label}</Text>
            </Pressable>
          ))}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hudBackdrop: {
    position: 'absolute',
    inset: 0,
    backgroundColor: '#050a16',
  },
  hudGlow: {
    position: 'absolute',
    top: -40,
    left: -60,
    backgroundColor: 'rgba(34, 211, 238, 0.14)',
    opacity: 0.6,
  },
  hudGlowSecondary: {
    position: 'absolute',
    bottom: -60,
    right: -40,
    backgroundColor: 'rgba(56, 189, 248, 0.12)',
    opacity: 0.6,
  },
  hudDot: {
    position: 'absolute',
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: 'rgba(110, 231, 255, 0.55)',
  },
  hudDotA: {
    top: 90,
    left: 22,
  },
  hudDotB: {
    top: 140,
    right: 28,
  },
  hudDotC: {
    bottom: 120,
    left: 40,
  },
  scanline: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: '40%',
    height: 2,
    backgroundColor: 'rgba(110, 231, 255, 0.1)',
  },
  stack: {
    width: '100%',
    gap: 12,
    justifyContent: 'space-between',
  },
  headerRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  hudTitle: {
    color: '#d7f3ff',
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 0.6,
  },
  hudSubtitle: {
    color: '#6c88a8',
    fontSize: 11,
    marginTop: 4,
  },
  statusRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  statusChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 14,
    backgroundColor: 'rgba(6, 14, 26, 0.45)',
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.5)',
    backgroundColor: 'rgba(110, 231, 255, 0.2)',
  },
  statusLabel: {
    color: '#8fa4bf',
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  statusValue: {
    color: '#d7f3ff',
    fontSize: 11,
    fontWeight: '700',
  },
  floatingCard: {
    borderRadius: 18,
    shadowColor: '#6ee7ff',
    shadowOpacity: 0.25,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
  },
  panelTitle: {
    color: '#cfe6ff',
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 0.6,
  },
  autoChip: {
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 8,
    backgroundColor: 'rgba(8, 16, 30, 0.5)',
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.25)',
  },
  autoChipActive: {
    backgroundColor: 'rgba(16, 42, 68, 0.7)',
    borderColor: 'rgba(110, 231, 255, 0.55)',
  },
  autoChipLabel: {
    color: '#dff4ff',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.1,
  },
  hero: {
    borderRadius: 999,
    borderWidth: 0,
    backgroundColor: 'rgba(7, 15, 27, 0.15)',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    shadowColor: '#6ee7ff',
    shadowOpacity: 0.4,
    shadowRadius: 26,
    shadowOffset: { width: 0, height: 8 },
  },
  heroWrap: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroGlow: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.16)',
    opacity: 0.8,
  },
  heroHalo: {
    position: 'absolute',
    width: 220,
    height: 220,
    borderRadius: 110,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.25)',
    opacity: 0.6,
  },
  heroRingOuter: {
    borderWidth: 2,
    borderColor: 'rgba(110, 231, 255, 0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroRingTicks: {
    position: 'absolute',
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.2)',
    borderStyle: 'dashed',
  },
  heroRingMid: {
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.65)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroRingInner: {
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.85)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroCore: {
    backgroundColor: '#6ee7ff',
    opacity: 0.75,
  },
  heroSweep: {
    position: 'absolute',
    width: 6,
    height: '120%',
    backgroundColor: 'rgba(110, 231, 255, 0.12)',
    right: '35%',
  },
  heroArcLeft: {
    position: 'absolute',
    left: -40,
    top: '20%',
    width: 80,
    height: 180,
    borderRadius: 80,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.2)',
    transform: [{ rotate: '-12deg' }],
  },
  heroArcRight: {
    position: 'absolute',
    right: -40,
    top: '20%',
    width: 80,
    height: 180,
    borderRadius: 80,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.2)',
    transform: [{ rotate: '12deg' }],
  },
  heroTitle: {
    marginTop: 12,
    color: '#dff4ff',
    fontSize: 20,
    fontWeight: '800',
    letterSpacing: 2,
  },
  heroSub: {
    marginTop: 4,
    color: '#7f93ad',
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  statLabel: {
    color: '#7f93ad',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  statValue: {
    color: '#e5eefb',
    fontSize: 18,
    fontWeight: '800',
  },
  miniRing: {
    marginTop: 6,
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 3,
    borderColor: '#6ee7ff',
    alignSelf: 'flex-start',
  },
  bottomRow: {
    flexDirection: 'row',
    gap: 10,
  },
  statCard: {
    borderRadius: 18,
    padding: 10,
    gap: 6,
    backgroundColor: 'rgba(6, 14, 26, 0.35)',
  },
  systemStrip: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  systemNode: {
    alignItems: 'center',
    gap: 6,
  },
  systemDot: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: '#6ee7ff',
    backgroundColor: 'rgba(110, 231, 255, 0.12)',
  },
  systemLabel: {
    color: '#a9bdd6',
    fontSize: 10,
    fontWeight: '600',
  },
  focusPanel: {
    borderRadius: 18,
    padding: 12,
    gap: 10,
    backgroundColor: 'rgba(6, 14, 26, 0.3)',
  },
  focusTitle: {
    color: '#e5eefb',
    fontSize: 14,
    fontWeight: '800',
  },
  focusSub: {
    marginTop: 4,
    color: '#7f93ad',
    fontSize: 12,
    lineHeight: 16,
  },
  hudActionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    justifyContent: 'space-between',
  },
  hudActionButton: {
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 0,
    backgroundColor: 'rgba(7, 15, 27, 0.6)',
  },
  hudActionText: {
    color: '#6ee7ff',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
});
