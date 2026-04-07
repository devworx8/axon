/**
 * ArcReactor — pure React Native arc-reactor visual.
 *
 * Desktop-faithful proportions (viewBox 420 × 420) with cinematic
 * boot-up ignition sequence matching the desktop CSS:
 *   reactor-orb-ignite   (6 s) — orb scales from 0 → full
 *   reactor-glow-ignite  (6 s) — glow halo expands with orb
 *   reactor-ring-boot    (1.8 s staggered) — rings fade in
 *   reactor-blade-unfold (0.8 s) — blades scale up
 *   reactor-boot-in      (2 s) — whole container fades from black
 *
 * Orb uses 6 concentric layers for a smoother radial gradient
 * (white → ice → light-cyan → mid-cyan → deep-cyan → dark-navy)
 * plus native shadow for the characteristic glow halo.
 *
 * States: idle | listening | speaking | thinking | sleep
 */
import React, { useEffect, useRef } from 'react';
import { Animated, Easing, Platform, Pressable, StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, RadialGradient, Rect, Stop } from 'react-native-svg';

/* ── Colour constants (exact desktop voice-reactor values) ──── */
const C = {
  cyan: '#22d3ee',
  cyanBright: '#67e8f9',
  white: '#ffffff',
  ice: '#f0fcff',
  lightCyan: '#dff8ff',
  midCyan: '#46dbff',
  deepCyan: '#1a8aad',
  darkCore: '#0a1630',
  bladeMid: '#2f6396',
  /* Ring strokes per state — match voiceVisualPalette() */
  ringIdle: 'rgba(100, 116, 139, 0.52)',
  ringListening: 'rgba(103, 232, 249, 0.92)',
  ringSpeaking: 'rgba(191, 219, 254, 0.86)',
  ringThinking: 'rgba(96, 165, 250, 0.72)',
  ringSleep: 'rgba(51, 65, 85, 0.3)',
  /* Glow per state */
  glowIdle: 'rgba(34, 211, 238, 0.18)',
  glowListening: 'rgba(34, 211, 238, 0.42)',
  glowSpeaking: 'rgba(96, 165, 250, 0.36)',
  glowThinking: 'rgba(59, 130, 246, 0.30)',
  beam: 'rgba(140, 243, 255, 0.35)',
} as const;

export type ReactorState = 'idle' | 'listening' | 'speaking' | 'thinking' | 'sleep';

type Props = {
  state: ReactorState;
  size?: number;
  onPress?: () => void;
  onLongPress?: () => void;
};

/* ── Helper: desktop 420-viewBox → proportional ─────────────── */
const P = (frac: number, sz: number) => frac * sz;

export function ArcReactor({ state, size = 280, onPress, onLongPress }: Props) {
  /* ── Animation values ──────────────────────────────── */
  const ring1Rot = useRef(new Animated.Value(0)).current;
  const ring2Rot = useRef(new Animated.Value(0)).current;
  const ring3Rot = useRef(new Animated.Value(0)).current;
  const coreScale = useRef(new Animated.Value(1)).current;
  const coreGlow = useRef(new Animated.Value(0.35)).current;
  const beamOpacity = useRef(new Animated.Value(0.28)).current;
  const ringOpacity = useRef(new Animated.Value(1)).current;
  const bladeOpacity = useRef(new Animated.Value(1)).current;

  /* Boot animation values */
  const bootFade = useRef(new Animated.Value(0)).current;         // whole reactor
  const orbIgnite = useRef(new Animated.Value(0)).current;        // orb scale 0→1
  const glowIgnite = useRef(new Animated.Value(0)).current;       // glow scale 0→1
  const ring1Boot = useRef(new Animated.Value(0)).current;        // ring opacity
  const ring2Boot = useRef(new Animated.Value(0)).current;
  const ring3Boot = useRef(new Animated.Value(0)).current;
  const bladeBoot = useRef(new Animated.Value(0)).current;        // blade scale+opacity
  const beamBoot = useRef(new Animated.Value(0)).current;
  const booted = useRef(false);
  const longPressTriggered = useRef(false);

  const handlePress = () => {
    if (longPressTriggered.current) {
      longPressTriggered.current = false;
      return;
    }
    onPress?.();
  };

  const handleLongPress = () => {
    longPressTriggered.current = true;
    onLongPress?.();
  };

  /* ── Boot-up ignition sequence (runs once on mount) ── */
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    Animated.sequence([
      /* Phase 1: reactor container fades in from black (0.8s) */
      Animated.timing(bootFade, {
        toValue: 1, duration: 800, easing: Easing.out(Easing.ease), useNativeDriver: true,
      }),
      /* Phase 2: parallel ignition */
      Animated.parallel([
        /* Orb grows: 0 → 1 over 3s with ease-in (matches reactor-orb-ignite) */
        Animated.timing(orbIgnite, {
          toValue: 1, duration: 3000, easing: Easing.bezier(0.25, 0.1, 0.25, 1), useNativeDriver: true,
        }),
        /* Glow follows orb slightly behind */
        Animated.sequence([
          Animated.delay(200),
          Animated.timing(glowIgnite, {
            toValue: 1, duration: 3000, easing: Easing.bezier(0.25, 0.1, 0.25, 1), useNativeDriver: true,
          }),
        ]),
        /* Rings fade in staggered (like stroke-dashoffset 900→0) */
        Animated.timing(ring1Boot, {
          toValue: 1, duration: 1800, easing: Easing.out(Easing.ease), useNativeDriver: true,
        }),
        Animated.sequence([
          Animated.delay(400),
          Animated.timing(ring2Boot, {
            toValue: 1, duration: 1800, easing: Easing.out(Easing.ease), useNativeDriver: true,
          }),
        ]),
        Animated.sequence([
          Animated.delay(800),
          Animated.timing(ring3Boot, {
            toValue: 1, duration: 1800, easing: Easing.out(Easing.ease), useNativeDriver: true,
          }),
        ]),
        /* Blades unfold slowly in sync with orb ignition */
        Animated.sequence([
          Animated.delay(1200),
          Animated.timing(bladeBoot, {
            toValue: 1, duration: 2800, easing: Easing.bezier(0.25, 0.1, 0.25, 1), useNativeDriver: true,
          }),
        ]),
        /* Beams sweep in after blades are mostly visible */
        Animated.sequence([
          Animated.delay(2400),
          Animated.timing(beamBoot, {
            toValue: 1, duration: 1600, easing: Easing.out(Easing.ease), useNativeDriver: true,
          }),
        ]),
      ]),
    ]).start();
  }, []);

  /* ── Persistent ring rotation ──────────────────────── */
  useEffect(() => {
    const speed = state === 'sleep' ? 80000 : state === 'thinking' ? 4000 : 20000;
    const anim1 = Animated.loop(
      Animated.timing(ring1Rot, { toValue: 1, duration: speed, easing: Easing.linear, useNativeDriver: true }),
    );
    const anim2 = Animated.loop(
      Animated.timing(ring2Rot, { toValue: 1, duration: speed * 1.4, easing: Easing.linear, useNativeDriver: true }),
    );
    const anim3 = Animated.loop(
      Animated.timing(ring3Rot, { toValue: 1, duration: speed * 1.8, easing: Easing.linear, useNativeDriver: true }),
    );
    anim1.start(); anim2.start(); anim3.start();
    return () => {
      anim1.stop(); anim2.stop(); anim3.stop();
      ring1Rot.setValue(0); ring2Rot.setValue(0); ring3Rot.setValue(0);
    };
  }, [state]);

  /* ── Core breathe / pulse ──────────────────────────── */
  useEffect(() => {
    if (state === 'sleep') {
      Animated.parallel([
        Animated.timing(coreScale, { toValue: 0.15, duration: 2500, useNativeDriver: true }),
        Animated.timing(coreGlow, { toValue: 0.06, duration: 2500, useNativeDriver: true }),
        Animated.timing(ringOpacity, { toValue: 0.12, duration: 3000, useNativeDriver: true }),
        Animated.timing(bladeOpacity, { toValue: 0.15, duration: 2500, useNativeDriver: true }),
        Animated.timing(beamOpacity, { toValue: 0.08, duration: 2500, useNativeDriver: true }),
      ]).start();
      return;
    }
    Animated.parallel([
      Animated.timing(ringOpacity, { toValue: 1, duration: 400, useNativeDriver: true }),
      Animated.timing(bladeOpacity, { toValue: 1, duration: 400, useNativeDriver: true }),
    ]).start();

    const pulseMs = state === 'listening' ? 1100 : state === 'speaking' ? 800 : 3200;
    const scMax = state === 'listening' ? 1.08 : state === 'speaking' ? 1.12 : 1.03;
    const glMax = state === 'listening' ? 0.65 : state === 'speaking' ? 0.55 : 0.35;
    const glMin = state === 'listening' ? 0.35 : state === 'speaking' ? 0.3 : 0.14;
    const bmMax = state === 'listening' ? 0.92 : state === 'speaking' ? 0.82 : 0.28;
    const bmMin = 0.18;

    const pulse = Animated.loop(Animated.sequence([
      Animated.timing(coreScale, { toValue: scMax, duration: pulseMs, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      Animated.timing(coreScale, { toValue: 1, duration: pulseMs, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
    ]));
    const glow = Animated.loop(Animated.sequence([
      Animated.timing(coreGlow, { toValue: glMax, duration: pulseMs, useNativeDriver: true }),
      Animated.timing(coreGlow, { toValue: glMin, duration: pulseMs, useNativeDriver: true }),
    ]));
    const beam = Animated.loop(Animated.sequence([
      Animated.timing(beamOpacity, { toValue: bmMax, duration: pulseMs * 1.5, useNativeDriver: true }),
      Animated.timing(beamOpacity, { toValue: bmMin, duration: pulseMs * 1.5, useNativeDriver: true }),
    ]));
    pulse.start(); glow.start(); beam.start();
    return () => { pulse.stop(); glow.stop(); beam.stop(); };
  }, [state]);

  /* ── Desktop-faithful proportions ─────────────────── */
  const cx = size / 2;
  const orbR   = P(52 / 420, size);
  const glowR  = P(70 / 420, size);
  const outR   = P(58 / 420, size);
  const maskR  = P(65 / 420, size);
  const tapR   = glowR;
  const ringRadii = [P(86 / 420, size), P(112 / 420, size), P(138 / 420, size)];
  const ringWidths = [1.8, 1.5, 1.2];

  const rotI = (v: Animated.Value) =>
    v.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  const rotR = (v: Animated.Value) =>
    v.interpolate({ inputRange: [0, 1], outputRange: ['360deg', '0deg'] });

  /* ── State-dependent colours ───────────────────────── */
  const ringColor =
    state === 'listening' ? C.ringListening
    : state === 'speaking' ? C.ringSpeaking
    : state === 'thinking' ? C.ringThinking
    : state === 'sleep' ? C.ringSleep
    : C.ringIdle;

  const glowColor =
    state === 'listening' ? C.glowListening
    : state === 'speaking' ? C.glowSpeaking
    : state === 'thinking' ? C.glowThinking
    : C.glowIdle;

  /* Orb gradient stops — exact desktop radialGradient (axon-orb-core) */
  const orbStops = state === 'speaking'
    ? [
        { offset: '0%', color: '#ffffff' },
        { offset: '22%', color: '#dbeafe' },
        { offset: '58%', color: '#3b82f6' },
        { offset: '100%', color: '#0a1630' },
      ]
    : [
        { offset: '0%', color: '#ffffff' },
        { offset: '22%', color: '#dff8ff' },
        { offset: '58%', color: '#46dbff' },
        { offset: '100%', color: '#0a1630' },
      ];

  /* Ring boot multipliers (staggered opacity from boot animation) */
  const ringBootValues = [ring1Boot, ring2Boot, ring3Boot];

  return (
    <Animated.View style={[styles.container, { width: size, height: size, opacity: bootFade }]}>

      {/* ── Rings ──────────────────────────────────── */}
      {ringRadii.map((r, i) => (
        <Animated.View
          key={`ring-${i}`}
          style={[
            styles.ring,
            {
              width: r * 2, height: r * 2, borderRadius: r,
              borderWidth: ringWidths[i],
              borderColor: ringColor,
              top: cx - r, left: cx - r,
              opacity: Animated.multiply(ringOpacity, ringBootValues[i]),
              transform: [{ rotate: i === 1 ? rotR(ring2Rot) : rotI(i === 2 ? ring3Rot : ring1Rot) }],
            },
          ]}
        />
      ))}

      {/* ── Blades: exact desktop SVG <path> geometry ── */}
      <Animated.View
        style={[StyleSheet.absoluteFillObject, {
          opacity: Animated.multiply(bladeOpacity, bladeBoot),
          transform: [{ scale: bladeBoot }],
        }]}
        pointerEvents="none"
      >
        <Svg width={size} height={size} viewBox="0 0 420 420">
          <Defs>
            <LinearGradient id="blade-fill" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor="#f7fbff" />
              <Stop offset="0.16" stopColor="#b9dbf7" />
              <Stop offset="0.52" stopColor="#2f6396" />
              <Stop offset="1" stopColor="#030d1f" />
            </LinearGradient>
            <LinearGradient id="blade-edge" x1="0" y1="0" x2="1" y2="0">
              <Stop offset="0" stopColor="#ffffff" stopOpacity={0.7} />
              <Stop offset="1" stopColor="#7fdcff" stopOpacity={0.05} />
            </LinearGradient>
          </Defs>
          {/* Top blade (diamond) */}
          <Path d="M210 38 L270 198 L210 286 L150 198 Z" fill="url(#blade-fill)" />
          <Path d="M210 38 L270 198" stroke="url(#blade-edge)" strokeWidth={3} fill="none" />
          <Path d="M210 38 L150 198" stroke="rgba(255,255,255,0.42)" strokeWidth={2} fill="none" />
          {/* Left blade */}
          <Path d="M66 334 L186 208 L170 348 Z" fill="url(#blade-fill)" />
          <Path d="M66 334 L186 208" stroke="url(#blade-edge)" strokeWidth={3} fill="none" />
          {/* Right blade */}
          <Path d="M354 334 L234 208 L250 348 Z" fill="url(#blade-fill)" />
          <Path d="M354 334 L234 208" stroke="url(#blade-edge)" strokeWidth={3} fill="none" />
        </Svg>
      </Animated.View>

      {/* ── Horizontal beams: gradient sweep ────────── */}
      <Animated.View
        style={[StyleSheet.absoluteFillObject, {
          opacity: Animated.multiply(beamOpacity, beamBoot),
        }]}
        pointerEvents="none"
      >
        <Svg width={size} height={size} viewBox="0 0 420 420">
          <Defs>
            <LinearGradient id="beam-grad" x1="0" y1="0.5" x2="1" y2="0.5">
              <Stop offset="0" stopColor="#7DD3FC" stopOpacity={0} />
              <Stop offset="0.5" stopColor="#8cf3ff" />
              <Stop offset="1" stopColor="#7DD3FC" stopOpacity={0} />
            </LinearGradient>
          </Defs>
          <Rect x={118} y={292} width={182} height={10} rx={5} fill="url(#beam-grad)" />
          <Rect x={131} y={305} width={157} height={10} rx={5} fill="url(#beam-grad)" />
        </Svg>
      </Animated.View>

      <Pressable
        onPress={handlePress}
        onLongPress={handleLongPress}
        delayLongPress={400}
        hitSlop={Math.max(20, Math.round(size * 0.08))}
        pressRetentionOffset={24}
        accessibilityRole="button"
        accessibilityLabel={state === 'sleep' ? 'Wake the Axon reactor' : 'Start or stop Axon voice capture'}
        style={[styles.coreTapTarget, {
          width: tapR * 2, height: tapR * 2, borderRadius: tapR,
          top: cx - tapR, left: cx - tapR,
        }]}
      >
        <View
          pointerEvents="none"
          style={[styles.coreMask, {
            width: maskR * 2, height: maskR * 2, borderRadius: maskR,
            top: tapR - maskR, left: tapR - maskR,
          }]}
        />
        <Animated.View
          pointerEvents="none"
          style={[styles.coreGlow, {
            width: glowR * 2, height: glowR * 2, borderRadius: glowR,
            top: tapR - glowR, left: tapR - glowR,
            backgroundColor: glowColor,
            opacity: Animated.multiply(coreGlow, glowIgnite),
            transform: [{ scale: Animated.multiply(coreScale, glowIgnite) }],
          }]}
        />
        <Animated.View
          pointerEvents="none"
          style={[styles.coreOrb, {
            width: orbR * 2, height: orbR * 2,
            top: tapR - orbR, left: tapR - orbR,
            transform: [{ scale: Animated.multiply(coreScale, orbIgnite) }],
            ...Platform.select({
              ios: {
                shadowColor: glowColor,
                shadowOffset: { width: 0, height: 0 },
                shadowOpacity: 0.9,
                shadowRadius: orbR * 0.6,
              },
              android: { elevation: 16 },
            }),
          }]}
        >
          <Svg width={orbR * 2} height={orbR * 2} viewBox="0 0 124 124">
            <Defs>
              <RadialGradient id="orb-core" cx="50%" cy="50%" r="60%">
                {orbStops.map((s, i) => (
                  <Stop key={i} offset={s.offset} stopColor={s.color} />
                ))}
              </RadialGradient>
            </Defs>
            <Circle cx="62" cy="62" r="62" fill="url(#orb-core)" />
          </Svg>
        </Animated.View>
        <Animated.View
          pointerEvents="none"
          style={[styles.coreOutline, {
            width: outR * 2, height: outR * 2, borderRadius: outR,
            top: tapR - outR, left: tapR - outR,
            opacity: Animated.multiply(coreGlow, orbIgnite),
          }]}
        />
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
  },
  ring: {
    position: 'absolute',
    borderStyle: 'dashed',
  },
  coreMask: {
    position: 'absolute',
    backgroundColor: '#000',
  },
  coreGlow: {
    position: 'absolute',
  },
  coreTapTarget: {
    position: 'absolute',
    overflow: 'visible',
  },
  coreOrb: {
    position: 'absolute',
  },
  coreOutline: {
    position: 'absolute',
    borderWidth: 1.5,
    borderColor: 'rgba(125, 211, 252, 0.25)',
  },
});
