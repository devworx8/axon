import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

function stateTone(state: string) {
  if (state === 'degraded') return '#fb7185';
  if (state === 'engaged' || state === 'speaking') return '#6ee7ff';
  if (state === 'armed' || state === 'listening') return '#34d399';
  return '#7f93ad';
}

export function AxonHudDial({
  state,
  wakePhrase,
  providerLabel,
}: {
  state: string;
  wakePhrase: string;
  providerLabel: string;
}) {
  const tone = stateTone(String(state || 'idle'));
  return (
    <View style={styles.shell}>
      <View style={[styles.ring, styles.ringOuter, { borderColor: `${tone}55` }]} />
      <View style={[styles.ring, styles.ringMid, { borderColor: `${tone}88` }]} />
      <View style={[styles.ring, styles.ringInner, { borderColor: tone }]} />
      <View style={[styles.core, { shadowColor: tone }]}>
        <Text style={styles.coreLabel}>AXON</Text>
        <Text style={[styles.coreState, { color: tone }]}>{String(state || 'idle').replace(/_/g, ' ')}</Text>
      </View>
      <View style={styles.footer}>
        <Text style={styles.footerLabel}>Wake</Text>
        <Text style={styles.footerValue}>{wakePhrase || 'Axon'}</Text>
        <Text style={styles.footerMeta}>{providerLabel}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 240,
    position: 'relative',
  },
  ring: {
    position: 'absolute',
    borderRadius: 999,
    borderWidth: 1,
  },
  ringOuter: {
    width: 210,
    height: 210,
  },
  ringMid: {
    width: 170,
    height: 170,
  },
  ringInner: {
    width: 128,
    height: 128,
    borderWidth: 3,
  },
  core: {
    width: 92,
    height: 92,
    borderRadius: 999,
    backgroundColor: '#08111f',
    borderWidth: 1,
    borderColor: '#22304a',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    shadowOpacity: 0.35,
    shadowRadius: 24,
  },
  coreLabel: {
    color: '#e5eefb',
    fontSize: 18,
    fontWeight: '900',
    letterSpacing: 2,
  },
  coreState: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  footer: {
    position: 'absolute',
    bottom: 8,
    alignItems: 'center',
    gap: 2,
  },
  footerLabel: {
    color: '#7f93ad',
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  footerValue: {
    color: '#e5eefb',
    fontSize: 13,
    fontWeight: '800',
  },
  footerMeta: {
    color: '#6ee7ff',
    fontSize: 11,
    fontWeight: '700',
  },
});
