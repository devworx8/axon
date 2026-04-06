import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

type VoiceTuningStepperProps = {
  label: string;
  value: string;
  minimum: number;
  maximum: number;
  step: number;
  onChange: (next: string) => void;
  hints: [string, string, string];
};

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function nextValue(current: string, delta: number, minimum: number, maximum: number, step: number) {
  const numeric = Number.parseFloat(String(current || '').trim());
  const fallback = minimum <= 1.0 && maximum >= 1.0 ? 1.0 : minimum;
  const resolved = Number.isFinite(numeric) ? numeric : fallback;
  const precision = Math.max(0, String(step).split('.')[1]?.length || 0);
  return clamp(resolved + delta, minimum, maximum).toFixed(precision);
}

export function VoiceTuningStepper({
  label,
  value,
  minimum,
  maximum,
  step,
  onChange,
  hints,
}: VoiceTuningStepperProps) {
  const numeric = Number.parseFloat(value);
  const canDecrease = Number.isFinite(numeric) ? numeric > minimum : true;
  const canIncrease = Number.isFinite(numeric) ? numeric < maximum : true;

  return (
    <View style={styles.stack}>
      <View style={styles.headerRow}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.value}>{value}</Text>
      </View>
      <View style={styles.controlsRow}>
        <Pressable
          onPress={() => onChange(nextValue(value, -step, minimum, maximum, step))}
          disabled={!canDecrease}
          style={[styles.button, !canDecrease ? styles.buttonDisabled : null]}
        >
          <Text style={styles.buttonText}>-</Text>
        </Pressable>
        <View style={styles.readout}>
          <Text style={styles.readoutText}>{value}</Text>
        </View>
        <Pressable
          onPress={() => onChange(nextValue(value, step, minimum, maximum, step))}
          disabled={!canIncrease}
          style={[styles.button, !canIncrease ? styles.buttonDisabled : null]}
        >
          <Text style={styles.buttonText}>+</Text>
        </Pressable>
      </View>
      <View style={styles.hintsRow}>
        <Text style={styles.hint}>{hints[0]}</Text>
        <Text style={styles.hint}>{hints[1]}</Text>
        <Text style={styles.hint}>{hints[2]}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: 8,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  label: {
    color: '#94a3b8',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  value: {
    color: '#7dd3fc',
    fontSize: 12,
    fontWeight: '800',
  },
  controlsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  button: {
    width: 42,
    height: 42,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#0b1627',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.45,
  },
  buttonText: {
    color: '#7dd3fc',
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 20,
  },
  readout: {
    flex: 1,
    minHeight: 42,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#22304a',
    backgroundColor: '#09111e',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  readoutText: {
    color: '#e5eefb',
    fontSize: 14,
    fontWeight: '700',
  },
  hintsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 8,
  },
  hint: {
    flex: 1,
    color: '#64748b',
    fontSize: 10,
    textAlign: 'center',
  },
});
