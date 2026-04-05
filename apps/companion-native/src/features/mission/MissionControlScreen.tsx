import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { SurfaceCard, SurfaceHeader } from '@/components/SurfaceCard';
import { PlatformSnapshot } from '@/types/companion';

export function MissionControlScreen({ snapshot }: { snapshot: PlatformSnapshot | null }) {
  return (
    <View style={styles.stack}>
      <SurfaceCard>
        <SurfaceHeader title="Axon Command Center" subtitle="Cinematic ops cockpit UI. Live wiring comes next." />
        <View style={styles.hudRow}>
          {['Ops', 'Voice', 'Attention', 'Systems', 'Runs'].map((label) => (
            <View key={label} style={styles.hudChip}>
              <View style={styles.hudChipRing} />
              <Text style={styles.hudChipText}>{label}</Text>
            </View>
          ))}
        </View>
      </SurfaceCard>

      <View style={styles.hero}>
        <View style={styles.heroGlow} />
        <View style={styles.heroRingOuter}>
          <View style={styles.heroRingMid}>
            <View style={styles.heroRingInner}>
              <View style={styles.heroCore} />
            </View>
          </View>
        </View>
        <Text style={styles.heroTitle}>A.X.O.N</Text>
        <Text style={styles.heroSub}>Voice ready · Command center online</Text>
      </View>

      <View style={styles.statsRow}>
        <SurfaceCard>
          <Text style={styles.statLabel}>CPU</Text>
          <Text style={styles.statValue}>53%</Text>
          <View style={styles.miniRing} />
        </SurfaceCard>
        <SurfaceCard>
          <Text style={styles.statLabel}>Memory</Text>
          <Text style={styles.statValue}>80%</Text>
          <View style={styles.miniRing} />
        </SurfaceCard>
      </View>

      <SurfaceCard>
        <SurfaceHeader title="Systems strip" subtitle="Visual placeholders for platform systems and sensors." />
        <View style={styles.systemStrip}>
          {['Runtime', 'Preview', 'Deploy', 'Signals', 'Vault'].map((item) => (
            <View key={item} style={styles.systemNode}>
              <View style={styles.systemDot} />
              <Text style={styles.systemLabel}>{item}</Text>
            </View>
          ))}
        </View>
      </SurfaceCard>

      <SurfaceCard>
        <SurfaceHeader title="Operator focus" subtitle="Primary scene for mission context and next action." />
        <View style={styles.focusPanel}>
          <Text style={styles.focusTitle}>{snapshot?.focus?.workspace?.name || 'Global platform view'}</Text>
          <Text style={styles.focusSub}>
            Axon is standing by. Voice loop is armed and awaiting command.
          </Text>
        </View>
      </SurfaceCard>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 14,
  },
  hudRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  hudChip: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.35)',
    backgroundColor: 'rgba(14, 24, 40, 0.8)',
    paddingHorizontal: 12,
    paddingVertical: 10,
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
    fontSize: 12,
    fontWeight: '700',
  },
  hero: {
    minHeight: 320,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.2)',
    backgroundColor: '#070f1b',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  heroGlow: {
    position: 'absolute',
    width: 320,
    height: 320,
    borderRadius: 160,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.12)',
    opacity: 0.6,
  },
  heroRingOuter: {
    width: 220,
    height: 220,
    borderRadius: 110,
    borderWidth: 2,
    borderColor: 'rgba(110, 231, 255, 0.35)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroRingMid: {
    width: 160,
    height: 160,
    borderRadius: 80,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroRingInner: {
    width: 110,
    height: 110,
    borderRadius: 55,
    borderWidth: 1,
    borderColor: 'rgba(110, 231, 255, 0.6)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroCore: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#6ee7ff',
    opacity: 0.6,
  },
  heroTitle: {
    marginTop: 18,
    color: '#dff4ff',
    fontSize: 22,
    fontWeight: '800',
    letterSpacing: 2,
  },
  heroSub: {
    marginTop: 6,
    color: '#7f93ad',
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  statsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  statLabel: {
    color: '#7f93ad',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  statValue: {
    color: '#e5eefb',
    fontSize: 20,
    fontWeight: '800',
  },
  miniRing: {
    marginTop: 8,
    width: 46,
    height: 46,
    borderRadius: 23,
    borderWidth: 3,
    borderColor: '#6ee7ff',
    alignSelf: 'flex-start',
  },
  systemStrip: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
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
    fontSize: 11,
    fontWeight: '600',
  },
  focusPanel: {
    borderWidth: 1,
    borderColor: '#22304a',
    borderRadius: 16,
    padding: 12,
    backgroundColor: '#0b1627',
  },
  focusTitle: {
    color: '#e5eefb',
    fontSize: 16,
    fontWeight: '800',
  },
  focusSub: {
    marginTop: 6,
    color: '#7f93ad',
    fontSize: 13,
    lineHeight: 18,
  },
});
