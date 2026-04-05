import React from 'react';
import { StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { PlatformSnapshot } from '@/types/companion';

export function MissionControlScreen({ snapshot }: { snapshot: PlatformSnapshot | null }) {
  const { width, height } = useWindowDimensions();
  const padding = Math.min(10, Math.max(6, width * 0.03));
  const maxWidth = Math.max(300, Math.min(width - padding * 2, 520));
  const ringSize = Math.max(170, Math.min(width * 0.68, height * 0.34));
  const ringInner = ringSize * 0.72;
  const ringMid = ringSize * 0.48;
  const coreSize = ringSize * 0.2;
  const attentionCounts = snapshot?.attention?.summary?.counts || {};
  const posture = String(snapshot?.posture || 'healthy').replace(/_/g, ' ');
  const focusName = snapshot?.focus?.workspace?.name || 'Global platform view';
  const axonState = snapshot?.axon?.armed ? String(snapshot?.axon?.monitoring_state || 'armed') : 'standby';
  const systemCount = snapshot?.systems?.length || 0;
  const runCount = snapshot?.sessions?.length || 0;
  const cpuValue = snapshot?.systems?.find((item) => String(item.key || item.label || '').toLowerCase().includes('cpu'))?.meta?.value;
  const memValue = snapshot?.systems?.find((item) => String(item.key || item.label || '').toLowerCase().includes('mem'))?.meta?.value;
  const cpuDisplay = typeof cpuValue === 'number' ? `${cpuValue}%` : '53%';
  const memDisplay = typeof memValue === 'number' ? `${memValue}%` : '80%';

  return (
    <View style={[styles.screen, { paddingHorizontal: padding, paddingTop: padding, paddingBottom: padding }]}>
      <View style={[styles.stack, { maxWidth }]}>
        <View style={styles.floatingCard}>
          <View style={styles.panel}>
            <Text style={styles.panelTitle}>Axon Command Center</Text>
            <View style={styles.hudRow}>
              {[
                { label: 'Ops', value: posture },
                { label: 'Voice', value: axonState },
                { label: 'Attention', value: `${Number(attentionCounts.now || 0)} now` },
                { label: 'Systems', value: `${systemCount} live` },
                { label: 'Runs', value: `${runCount} active` },
              ].map((item) => (
                <View key={item.label} style={styles.hudChip}>
                  <View style={styles.hudChipRing} />
                  <View>
                    <Text style={styles.hudChipText}>{item.label}</Text>
                    <Text style={styles.hudChipValue}>{item.value}</Text>
                  </View>
                </View>
              ))}
            </View>
          </View>
        </View>

        <View style={[styles.hero, { height: ringSize + 30 }]}>
          <View style={[styles.heroGlow, { width: ringSize + 120, height: ringSize + 120, borderRadius: (ringSize + 120) / 2 }]} />
          <View style={styles.heroHalo} />
          <View style={[styles.heroRingOuter, { width: ringSize, height: ringSize, borderRadius: ringSize / 2 }]}>
            <View style={[styles.heroRingMid, { width: ringInner, height: ringInner, borderRadius: ringInner / 2 }]}>
              <View style={[styles.heroRingInner, { width: ringMid, height: ringMid, borderRadius: ringMid / 2 }]}>
                <View style={[styles.heroCore, { width: coreSize, height: coreSize, borderRadius: coreSize / 2 }]} />
              </View>
            </View>
          </View>
          <View style={styles.heroSweep} />
          <Text style={styles.heroTitle}>A.X.O.N</Text>
          <Text style={styles.heroSub}>Voice ready · Command center online</Text>
        </View>

        <View style={styles.metricsRow}>
          <View style={styles.floatingCard}>
            <View style={styles.panel}>
              <Text style={styles.statLabel}>CPU</Text>
              <Text style={styles.statValue}>{cpuDisplay}</Text>
              <View style={styles.miniRing} />
            </View>
          </View>
          <View style={styles.floatingCard}>
            <View style={styles.panel}>
              <Text style={styles.statLabel}>Memory</Text>
              <Text style={styles.statValue}>{memDisplay}</Text>
              <View style={styles.miniRing} />
            </View>
          </View>
        </View>

        <View style={styles.floatingCard}>
          <View style={styles.panel}>
            <Text style={styles.panelTitle}>Systems + Focus</Text>
            <View style={styles.systemStrip}>
              {(snapshot?.systems && snapshot.systems.length
                ? snapshot.systems.slice(0, 5).map((item) => item.label || item.key || 'System')
                : ['Runtime', 'Preview', 'Deploy', 'Signals', 'Vault']
              ).map((item) => (
                  <View key={String(item)} style={styles.systemNode}>
                    <View style={styles.systemDot} />
                    <Text style={styles.systemLabel}>{String(item)}</Text>
                  </View>
                ))}
            </View>
            <View style={styles.focusPanel}>
              <Text style={styles.focusTitle}>{focusName}</Text>
              <Text style={styles.focusSub}>
                {snapshot?.axon?.armed ? 'Voice loop armed.' : 'Voice loop ready.'} Awaiting command.
              </Text>
            </View>
          </View>
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
  stack: {
    width: '100%',
    gap: 6,
  },
  floatingCard: {
    borderRadius: 18,
    shadowColor: '#6ee7ff',
    shadowOpacity: 0.25,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
  },
  panel: {
    borderRadius: 18,
    padding: 12,
    gap: 8,
    backgroundColor: 'rgba(8, 16, 30, 0.55)',
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.14)',
  },
  panelTitle: {
    color: '#cfe6ff',
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 0.6,
  },
  hudRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  hudChip: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.22)',
    backgroundColor: 'rgba(10, 18, 32, 0.6)',
    paddingHorizontal: 10,
    paddingVertical: 6,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  hudChipRing: {
    width: 14,
    height: 14,
    borderRadius: 999,
    borderWidth: 2,
    borderColor: '#6ee7ff',
  },
  hudChipText: {
    color: '#d8ecff',
    fontSize: 11,
    fontWeight: '700',
  },
  hudChipValue: {
    color: '#7f93ad',
    fontSize: 10,
    fontWeight: '600',
  },
  hero: {
    borderRadius: 24,
    borderWidth: 0,
    backgroundColor: 'rgba(7, 15, 27, 0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    shadowColor: '#6ee7ff',
    shadowOpacity: 0.35,
    shadowRadius: 22,
    shadowOffset: { width: 0, height: 8 },
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
    opacity: 0.6,
  },
  heroSweep: {
    position: 'absolute',
    width: 6,
    height: '120%',
    backgroundColor: 'rgba(110, 231, 255, 0.12)',
    transform: [{ rotate: '20deg' }],
    right: '35%',
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
  metricsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
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
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.18)',
    borderRadius: 16,
    padding: 10,
    backgroundColor: 'rgba(8, 16, 30, 0.6)',
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
});
