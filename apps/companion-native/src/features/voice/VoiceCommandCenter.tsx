/**
 * VoiceCommandCenter — Full-screen immersive voice mode.
 *
 * This IS the main app experience — the reactor fills the screen
 * like JARVIS's interface. Cinematic boot, radial glow backdrop,
 * floating status overlays, and JARVIS-style TTS greetings.
 *
 * Desktop reference: voice.html (fixed inset-0 z-[999] overlay)
 *   - bg-slate-950/95 backdrop-blur-xl
 *   - radial-gradient backdrop (cyan 30%, blue 70%)
 *   - Large reactor centered
 *   - Status + "Tap the orb to speak"
 *   - Floating transcript/response that appear only when active
 *   - Mic controls + quick-command only when needed
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as Speech from 'expo-speech';

import { ArcReactor, type ReactorState } from '@/components/ArcReactor';
import { StatusPill } from '@/components/StatusPill';
import { useAxonBootSound } from '@/features/axon/useAxonBootSound';
import {
  buildVoiceLiveIndicator,
  voiceCenterStatusCaption,
  voiceCenterStatusLabel,
} from '@/features/voice/voiceCenterStatus';
import { isVoiceTranscriptionReady } from '@/features/voice/voiceReadiness';
import { pickBestVoice, GREETING_RATE, GREETING_PITCH } from '@/utils/pickVoice';
import type { ApprovalRequired, AxonModeStatus } from '@/types/companion';
import type { LocalVoiceStatus } from '@/types/companion';

/* ── Colour constants ────────────────────────────────────────── */
const C = {
  bg: '#020617',
  cyan: '#22d3ee',
  cyanGlow: 'rgba(34, 211, 238, 0.08)',
  cyanBorder: 'rgba(34, 211, 238, 0.25)',
  glass: 'rgba(15, 23, 42, 0.75)',
  glassBorder: 'rgba(148, 163, 184, 0.12)',
  text: '#f1f5f9',
  textSec: '#94a3b8',
  muted: '#64748b',
  dim: '#475569',
  emerald: '#34d399',
  rose: '#fb7185',
  amber: '#fbbf24',
  border: '#1e293b',
} as const;

/* ── JARVIS greetings ────────────────────────────────────────── */
function pickBootGreeting(): string {
  const hour = new Date().getHours();
  const timeWord = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
  const pool = [
    `Good ${timeWord}, Sir. All systems are online.`,
    `Reactor online. Standing by, Sir.`,
    `Good ${timeWord}, Sir. Axon is ready for your command.`,
    `Systems nominal. How can I help you, Sir?`,
    `Online and operational. Good ${timeWord}, Sir.`,
  ];
  return pool[Math.floor(Math.random() * pool.length)];
}

function pickSleepGoodbye(): string {
  const pool = [
    "Going offline, Sir. I'll be here when you need me.",
    'Reactor powering down. Rest well, Sir.',
    'Standing down, Sir. Systems on standby.',
  ];
  return pool[Math.floor(Math.random() * pool.length)];
}

/* ── Props type ──────────────────────────────────────────────── */
type Props = {
  onSubmit: (text: string) => void;
  sending?: boolean;
  transcript?: string;
  response?: string;
  backend?: string;
  tokensUsed?: number;
  approval?: ApprovalRequired | null;
  voiceMode?: string;
  error?: string | null;
  workspaceLabel?: string;
  onOpenSession?: () => void;
  speaking?: boolean;
  onSpeak?: () => void;
  onSpeakText?: (text: string) => void;
  onStopSpeaking?: () => void;
  liveVoiceStatus?: LocalVoiceStatus | null;
  checkingVoiceStatus?: boolean;
  recording?: boolean;
  transcribing?: boolean;
  recordingDuration?: string;
  handsFree?: boolean;
  liveTranscript?: string;
  liveEngine?: string;
  liveError?: string | null;
  onStartLiveVoice?: () => void;
  onStopLiveVoice?: () => void;
  onRefreshLiveVoice?: () => void;
  axon?: AxonModeStatus | null;
  axonWakePhrase: string;
  onChangeAxonWakePhrase: (value: string) => void;
  axonBusy?: boolean;
  axonError?: string | null;
  onArmAxon?: () => void;
  onDisarmAxon?: () => void;
  onExitVoice?: () => void;
};

/* ══════════════════════════════════════════════════════════════ */
export function VoiceScreen(props: Props) {
  const {
    onSubmit, sending, transcript, response, backend,
    approval, error, speaking, onSpeak, onSpeakText, onStopSpeaking,
    liveVoiceStatus, checkingVoiceStatus,
    recording, transcribing, recordingDuration, handsFree, liveTranscript,
    liveEngine, liveError, onStartLiveVoice, onStopLiveVoice, onRefreshLiveVoice,
    axon, axonBusy, onArmAxon, onDisarmAxon,
    voiceMode, workspaceLabel,
  } = props;

  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  /* Reactor fills most of the screen — cinematic sizing */
  const reactorSize = Math.min(width * 0.82, height * 0.42, 360);

  /* ── Boot sound (reactor power-up) ─────────────────── */
  const { play: playBootSound } = useAxonBootSound(true);

  /* ── Shared voice identifier (same prefs as desktop) ── */
  const [voiceId, setVoiceId] = useState<string | undefined>();
  useEffect(() => { pickBestVoice().then(setVoiceId); }, []);

  /* ── Reactor state machine ─────────────────────────── */
  const [asleep, setAsleep] = useState(false);
  const greetingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [greetingText, setGreetingText] = useState('');
  const greetingFade = useRef(new Animated.Value(0)).current;

  /* Cinematic backdrop glow pulse */
  const backdropGlow = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(backdropGlow, {
      toValue: 1, duration: 4000, useNativeDriver: true,
    }).start();
  }, []);

  const reactorState: ReactorState = useMemo(() => {
    if (asleep) return 'sleep';
    if (sending || transcribing) return 'thinking';
    if (recording) return 'listening';
    if (speaking) return 'speaking';
    return 'idle';
  }, [asleep, sending, transcribing, recording, speaking]);

  /* ── Greeting TTS (Azure cloud → device fallback) ── */
  const speakGreeting = useCallback((text: string, spoken = true) => {
    setGreetingText(text);
    Animated.timing(greetingFade, { toValue: 1, duration: 600, useNativeDriver: true }).start();
    const fadeOut = () => {
      Animated.timing(greetingFade, { toValue: 0, duration: 2000, useNativeDriver: true }).start();
    };
    if (!spoken) {
      setTimeout(fadeOut, Math.max(1800, text.length * 48));
      return;
    }
    if (onSpeakText) {
      /* Route through useAxonSpeech → Azure TTS pipeline */
      onSpeakText(text);
      /* Approximate fade after speech duration */
      setTimeout(fadeOut, Math.max(2000, text.length * 70));
    } else {
      /* Fallback to device TTS */
      Speech.speak(text, {
        rate: GREETING_RATE,
        pitch: GREETING_PITCH,
        ...(voiceId ? { voice: voiceId } : { language: 'en-GB' }),
        onDone: fadeOut,
      });
    }
  }, [voiceId, onSpeakText]);

  /* ── Reactor orb tap: primary voice control ──────── */
  /* Tap = start/stop listening.  Long-press = sleep/wake toggle. */
  const liveReady = isVoiceTranscriptionReady(liveVoiceStatus);

  const handleReactorTap = useCallback(() => {
    if (asleep) {
      /* Wake on tap if sleeping */
      setAsleep(false);
      playBootSound();
      greetingTimer.current = setTimeout(() => {
        speakGreeting(
          handsFree ? 'Axon online. Hands-free listening engaged.' : pickBootGreeting(),
          !handsFree,
        );
      }, 1800);
      return;
    }
    if (recording) {
      /* Tap while recording → stop & submit */
      onStopLiveVoice?.();
    } else if (!sending && !transcribing) {
      /* Always attempt a fresh start; startRecording re-checks readiness. */
      onStartLiveVoice?.();
    }
  }, [asleep, handsFree, onStartLiveVoice, onStopLiveVoice, playBootSound, recording, sending, speakGreeting, transcribing]);

  const handleReactorLongPress = useCallback(() => {
    if (asleep) return; /* already sleeping — normal tap wakes */
    if (greetingTimer.current) clearTimeout(greetingTimer.current);
    Speech.stop();
    onStopSpeaking?.();
    speakGreeting(pickSleepGoodbye());
    setAsleep(true);
  }, [asleep, speakGreeting, onStopSpeaking]);

  /* Initial boot greeting (delayed to match reactor ignition) */
  useEffect(() => {
    playBootSound();
    greetingTimer.current = setTimeout(() => {
      speakGreeting(
        handsFree ? 'Axon online. Hands-free listening engaged.' : pickBootGreeting(),
        !handsFree,
      );
    }, 4000);
    return () => { if (greetingTimer.current) clearTimeout(greetingTimer.current); };
  }, [handsFree, playBootSound, speakGreeting]);

  /* ── Status labels ─────────────────────────────────── */
  const statusLabel = useMemo(() => voiceCenterStatusLabel({
    asleep,
    sending,
    transcribing,
    recording,
    speaking,
    recordingDuration,
  }), [asleep, sending, transcribing, recording, speaking, recordingDuration]);

  const statusCaption = useMemo(() => voiceCenterStatusCaption({
    asleep,
    sending,
    transcribing,
    recording,
    speaking,
    liveReady,
    checkingVoiceStatus,
    liveError,
  }), [asleep, sending, transcribing, recording, speaking, liveReady, checkingVoiceStatus, liveError]);

  const liveIndicator = useMemo(() => buildVoiceLiveIndicator({
    recording,
    transcribing,
    sending,
    liveReady,
    checkingVoiceStatus,
    liveError,
  }), [recording, transcribing, sending, liveReady, checkingVoiceStatus, liveError]);

  const handleLiveIndicatorPress = useCallback(() => {
    if (recording) {
      onStopLiveVoice?.();
      return;
    }
    if (sending || transcribing) {
      return;
    }
    if (liveReady) {
      onStartLiveVoice?.();
      return;
    }
    onStartLiveVoice?.();
  }, [recording, sending, transcribing, liveReady, onStartLiveVoice, onStopLiveVoice]);

  const statusColor =
    reactorState === 'listening' ? C.cyan
    : reactorState === 'speaking' ? '#60a5fa'
    : reactorState === 'thinking' ? C.amber
    : C.text;
  const transcriptBody = liveTranscript || transcript || (recording ? 'Listening…' : 'Waiting for a voice command…');
  const responseBody = response
    || (sending
      ? 'Axon is processing your request…'
      : approval
        ? (approval.message || 'Approval is required before Axon can continue.')
        : 'The latest voice response will appear here.');
  const awaitingBanner = Boolean(checkingVoiceStatus || sending || transcribing || approval);
  const liveDetail = String(
    liveVoiceStatus?.detail
    || (liveReady
      ? (handsFree
        ? 'Live voice link ready. Axon starts listening automatically and shows live transcript as you speak.'
        : 'Live voice link ready. Tap the reactor or the command button to start listening.')
      : 'Voice is offline. Refresh the link or verify the desktop Axon URL from Settings.')
  ).trim();
  const handlePrimaryAction = useCallback(() => {
    if (recording) {
      onStopLiveVoice?.();
      return;
    }
    handleReactorTap();
  }, [handleReactorTap, onStopLiveVoice, recording]);

  /* ── Quick-command text input ───────────────────────── */
  const [commandText, setCommandText] = useState('');
  const [showControls, setShowControls] = useState(false);

  const handleSubmit = useCallback(() => {
    const text = commandText.trim();
    if (!text || sending) return;
    onSubmit(text);
    setCommandText('');
  }, [commandText, sending, onSubmit]);

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      {/* ── Exit button (top-right, goes to dashboard) ── */}
      {props.onExitVoice && (
        <Pressable style={[styles.exitBtn, { top: insets.top + 8 }]} onPress={props.onExitVoice}>
          <Text style={styles.exitBtnText}>◆</Text>
        </Pressable>
      )}
      <Pressable
        style={[styles.liveIndicatorBtn, { top: insets.top + 56 }]}
        onPress={handleLiveIndicatorPress}
        disabled={sending || transcribing}
      >
        <StatusPill label={liveIndicator.label} tone={liveIndicator.tone} />
      </Pressable>

      {/* ── Cinematic radial glow backdrop ──────────── */}
      <Animated.View style={[styles.backdrop, { opacity: backdropGlow }]}>
        <View style={styles.glowTop} />
        <View style={styles.glowBottom} />
      </Animated.View>

      {/* ── Eyebrow + provider chips ──────────────────── */}
      <View style={styles.header}>
        <Text style={styles.eyebrow}>AXON VOICE MODE</Text>
        <View style={styles.providerRow}>
          <StatusPill label={axon?.armed ? 'Armed' : 'Standby'} tone={axon?.armed ? 'accent' : 'neutral'} />
          <StatusPill label={voiceMode === 'live' ? 'Live' : voiceMode || 'Push-to-talk'} tone="accent" />
          {handsFree ? <StatusPill label="Hands-free" tone="accent" /> : null}
          {liveVoiceStatus?.preferred_mode ? <StatusPill label={String(liveVoiceStatus.preferred_mode)} tone="neutral" /> : null}
          {liveEngine ? <StatusPill label={liveEngine} tone="neutral" /> : null}
          {backend ? <StatusPill label={backend} tone="neutral" /> : null}
          {workspaceLabel ? <StatusPill label={workspaceLabel} tone="neutral" /> : null}
        </View>
        <Text style={styles.providerDetail}>{liveDetail}</Text>
      </View>

      {/* ── ARC REACTOR (hero — centered) ─────────────── */}
      <View style={styles.reactorZone}>
        <View style={{ position: 'relative' }}>
          <ArcReactor state={reactorState} size={reactorSize} onPress={handleReactorTap} onLongPress={handleReactorLongPress} />
          {/* HUD corner brackets — desktop voice-hud */}
          <View style={styles.hudTL} />
          <View style={styles.hudBR} />
        </View>
      </View>

      {/* ── Status text (below reactor) ───────────────── */}
      <View style={styles.statusBlock}>
        <Text style={[styles.statusLabel, { color: statusColor }]}>
          {statusLabel}
        </Text>
        <Text style={styles.statusCaption}>{statusCaption}</Text>
        {greetingText ? (
          <Animated.Text style={[styles.greeting, { opacity: greetingFade }]}>
            "{greetingText}"
          </Animated.Text>
        ) : null}
      </View>

      <View style={styles.actionRail}>
        <Pressable
          style={[styles.primaryRailAction, (sending || transcribing) ? styles.railActionDisabled : null]}
          onPress={handlePrimaryAction}
          disabled={sending || transcribing}
        >
          <Text style={styles.primaryRailActionText}>
            {recording ? 'Stop and run' : liveReady ? (handsFree ? 'Restart listening' : 'Start listening') : 'Retry voice'}
          </Text>
        </Pressable>
        <Pressable
          style={[styles.secondaryRailAction, checkingVoiceStatus ? styles.railActionDisabled : null]}
          onPress={onRefreshLiveVoice}
          disabled={checkingVoiceStatus}
        >
          <Text style={styles.secondaryRailActionText}>
            {checkingVoiceStatus ? 'Checking…' : 'Refresh link'}
          </Text>
        </Pressable>
      </View>

      {awaitingBanner ? (
        <View style={styles.awaitingBanner}>
          <Text style={styles.awaitingBannerLabel}>Conversation hold</Text>
          <Text style={styles.awaitingBannerDetail}>{approval?.resume_task || statusCaption}</Text>
        </View>
      ) : null}

      <View style={styles.panels}>
        <View style={[styles.floatPanel, recording ? styles.floatPanelGlow : null]}>
          <View style={styles.panelHeader}>
            <View style={[styles.panelDot, recording && styles.panelDotActive]} />
            <Text style={styles.panelLabel}>TRANSCRIPT</Text>
          </View>
          <ScrollView style={styles.transcriptPanelScroll} nestedScrollEnabled>
            <Text style={[styles.panelBody, transcriptBody === 'Waiting for a voice command…' ? styles.panelBodyMuted : null]}>
              {transcriptBody}
            </Text>
          </ScrollView>
        </View>
        <View style={[styles.floatPanel, (response || sending || approval) ? styles.floatPanelGlow : null]}>
          <View style={styles.panelHeader}>
            <View style={[styles.panelDot, response ? styles.panelDotCyan : undefined]} />
            <Text style={[styles.panelLabel, response ? { color: C.cyan } : null]}>RESPONSE</Text>
          </View>
          <ScrollView style={styles.responsePanelScroll} nestedScrollEnabled>
            <Text style={[styles.panelBody, (response || approval) ? { color: C.text } : styles.panelBodyMuted]}>
              {responseBody}
            </Text>
          </ScrollView>
          {response ? (
            <View style={styles.speakRow}>
              {speaking ? (
                <Pressable style={styles.speakBtn} onPress={onStopSpeaking}>
                  <Text style={styles.speakBtnText}>■ Stop</Text>
                </Pressable>
              ) : (
                <Pressable style={styles.speakBtn} onPress={onSpeak}>
                  <Text style={styles.speakBtnText}>▶ Replay</Text>
                </Pressable>
              )}
            </View>
          ) : null}
        </View>
      </View>

      {/* ── Error / approval ──────────────────────────── */}
      {(error || liveError) && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error || liveError}</Text>
        </View>
      )}
      {approval && (
        <Pressable onPress={props.onOpenSession} style={styles.approvalBox}>
          <Text style={styles.approvalLabel}>⚠ Approval Required</Text>
          <Text style={styles.approvalBody}>{approval.message || 'Axon needs your permission.'}</Text>
          <Text style={styles.approvalAction}>Open session →</Text>
        </Pressable>
      )}

      {/* ── Minimal bottom controls ─────────────────── */}
      <View style={styles.bottomControls}>
        {/* Compact status — single line */}
        <View style={styles.micStatusPills}>
          <StatusPill
            label={
              recording ? `Recording ${recordingDuration || ''}`
              : transcribing ? 'Transcribing…'
              : liveReady ? 'Ready'
              : checkingVoiceStatus ? 'Checking…'
              : 'Offline'
            }
            tone={recording ? 'danger' : transcribing ? 'warn' : liveReady ? 'ok' : 'neutral'}
          />
          {liveVoiceStatus?.preferred_mode ? (
            <StatusPill label={String(liveVoiceStatus.preferred_mode)} tone="accent" />
          ) : null}
          {axon?.armed ? (
            <Pressable onPress={onDisarmAxon} disabled={axonBusy}>
              <StatusPill label="Armed" tone="accent" />
            </Pressable>
          ) : (
            <Pressable onPress={onArmAxon} disabled={axonBusy}>
              <StatusPill label="Standby" tone="neutral" />
            </Pressable>
          )}
        </View>

        {/* Long-press hint */}
        <Text style={styles.longPressHint}>Hold reactor to power down</Text>

        {/* Expand toggle for text input */}
        <Pressable style={styles.expandToggle} onPress={() => setShowControls(v => !v)}>
          <Text style={styles.expandText}>{showControls ? '▾ Hide command bar' : '▸ Type a command'}</Text>
        </Pressable>

        {showControls && (
          <View style={styles.commandBar}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.promptRow}>
              {['Status report', 'What needs attention?', 'Inspect workspace'].map(p => (
                <Pressable key={p} style={styles.promptChip} onPress={() => setCommandText(p)}>
                  <Text style={styles.promptChipText} numberOfLines={1}>{p}</Text>
                </Pressable>
              ))}
            </ScrollView>
            <View style={styles.inputRow}>
              <TextInput
                style={styles.textInput}
                value={commandText}
                onChangeText={setCommandText}
                placeholder="Type a command…"
                placeholderTextColor={C.dim}
                returnKeyType="send"
                onSubmitEditing={handleSubmit}
                editable={!sending}
              />
              <Pressable
                style={[styles.sendBtn, (!commandText.trim() || sending) && styles.sendBtnDisabled]}
                onPress={handleSubmit}
                disabled={!commandText.trim() || sending}
              >
                <Text style={styles.sendBtnText}>Run</Text>
              </Pressable>
            </View>
          </View>
        )}
      </View>
    </View>
  );
}

/* ── Styles ─────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: C.bg,
    alignItems: 'center',
  },

  /* Cinematic radial glow backdrop */
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    overflow: 'hidden',
  },
  glowTop: {
    position: 'absolute',
    top: '-10%',
    left: '10%',
    width: '80%',
    height: '50%',
    borderRadius: 9999,
    backgroundColor: 'rgba(34, 211, 238, 0.06)',
  },
  glowBottom: {
    position: 'absolute',
    bottom: '5%',
    left: '15%',
    width: '70%',
    height: '40%',
    borderRadius: 9999,
    backgroundColor: 'rgba(59, 130, 246, 0.04)',
  },

  /* Header */
  header: {
    alignItems: 'center',
    gap: 8,
    paddingTop: 12,
    paddingHorizontal: 16,
    zIndex: 1,
  },
  eyebrow: {
    fontSize: 10,
    letterSpacing: 3.5,
    textTransform: 'uppercase',
    color: C.muted,
  },
  providerRow: {
    flexDirection: 'row',
    gap: 6,
    flexWrap: 'wrap',
    justifyContent: 'center',
  },
  providerDetail: {
    maxWidth: 340,
    fontSize: 12,
    lineHeight: 18,
    color: C.textSec,
    textAlign: 'center',
  },

  /* Reactor — hero center (fixed, not flex:1 — leave room for response) */
  reactorZone: {
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 8,
  },

  /* HUD corner brackets */
  hudTL: {
    position: 'absolute',
    top: -8,
    left: -8,
    width: 32,
    height: 32,
    borderTopWidth: 2,
    borderLeftWidth: 2,
    borderColor: 'rgba(0, 212, 255, 0.35)',
  },
  hudBR: {
    position: 'absolute',
    bottom: -8,
    right: -8,
    width: 32,
    height: 32,
    borderBottomWidth: 2,
    borderRightWidth: 2,
    borderColor: 'rgba(0, 212, 255, 0.35)',
  },

  /* Exit to dashboard */
  exitBtn: {
    position: 'absolute',
    right: 12,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
    borderWidth: 1,
    borderColor: 'rgba(148, 163, 184, 0.15)',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 10,
  },
  exitBtnText: {
    fontSize: 18,
    color: 'rgba(148, 163, 184, 0.6)',
  },
  liveIndicatorBtn: {
    position: 'absolute',
    right: 12,
    zIndex: 10,
  },

  /* Status */
  statusBlock: {
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 24,
    paddingBottom: 8,
  },
  statusLabel: {
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  statusCaption: {
    fontSize: 10,
    letterSpacing: 1.8,
    textTransform: 'uppercase',
    color: C.muted,
    textAlign: 'center',
  },
  greeting: {
    marginTop: 4,
    fontSize: 13,
    fontStyle: 'italic',
    color: C.textSec,
    textAlign: 'center',
  },
  actionRail: {
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: 16,
    paddingBottom: 10,
  },
  primaryRailAction: {
    flex: 1,
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 16,
    backgroundColor: 'rgba(34, 211, 238, 0.18)',
    borderWidth: 1,
    borderColor: C.cyanBorder,
  },
  primaryRailActionText: {
    fontSize: 14,
    fontWeight: '700',
    color: C.cyan,
  },
  secondaryRailAction: {
    minWidth: 118,
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: 'rgba(15, 23, 42, 0.72)',
    borderWidth: 1,
    borderColor: C.border,
  },
  secondaryRailActionText: {
    fontSize: 13,
    fontWeight: '600',
    color: C.textSec,
  },
  railActionDisabled: {
    opacity: 0.55,
  },
  awaitingBanner: {
    width: '100%',
    marginBottom: 10,
    paddingHorizontal: 16,
    gap: 4,
  },
  awaitingBannerLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
    textTransform: 'uppercase',
    color: C.amber,
  },
  awaitingBannerDetail: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.22)',
    backgroundColor: 'rgba(251, 191, 36, 0.08)',
    color: C.textSec,
    fontSize: 12,
    lineHeight: 17,
  },

  /* Floating panels — glass morphism */
  panels: {
    flex: 1,
    width: '100%',
    paddingHorizontal: 16,
    gap: 8,
  },
  floatPanel: {
    padding: 14,
    borderRadius: 16,
    backgroundColor: C.glass,
    borderWidth: 1,
    borderColor: C.glassBorder,
  },
  floatPanelGlow: {
    borderColor: 'rgba(34, 211, 238, 0.2)',
    shadowColor: C.cyan,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
  },
  panelHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 6,
  },
  panelDot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: C.dim,
  },
  panelDotActive: {
    backgroundColor: C.rose,
  },
  panelDotCyan: {
    backgroundColor: C.cyan,
  },
  panelLabel: {
    fontSize: 10,
    letterSpacing: 2,
    textTransform: 'uppercase',
    fontWeight: '600',
    color: C.muted,
  },
  panelBody: {
    fontSize: 14,
    lineHeight: 20,
    color: C.textSec,
  },
  panelBodyMuted: {
    color: C.muted,
  },
  speakRow: {
    flexDirection: 'row',
    marginTop: 8,
    gap: 8,
  },
  speakBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
    backgroundColor: 'rgba(34, 211, 238, 0.12)',
    borderWidth: 1,
    borderColor: C.cyanBorder,
  },
  speakBtnText: {
    fontSize: 12,
    fontWeight: '600',
    color: C.cyan,
  },
  responsePanelScroll: {
    maxHeight: 180,
  },
  transcriptPanelScroll: {
    maxHeight: 110,
  },

  /* Error / Approval */
  errorBox: {
    marginHorizontal: 16,
    padding: 12,
    borderRadius: 14,
    backgroundColor: 'rgba(251, 113, 133, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(251, 113, 133, 0.25)',
  },
  errorText: {
    fontSize: 13,
    color: C.rose,
  },
  approvalBox: {
    marginHorizontal: 16,
    padding: 14,
    borderRadius: 16,
    backgroundColor: 'rgba(251, 191, 36, 0.08)',
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.25)',
    gap: 6,
  },
  approvalLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: C.amber,
  },
  approvalBody: {
    fontSize: 13,
    color: C.textSec,
    lineHeight: 18,
  },
  approvalAction: {
    fontSize: 13,
    fontWeight: '600',
    color: C.cyan,
    marginTop: 2,
  },

  /* Bottom controls */
  bottomControls: {
    width: '100%',
    paddingHorizontal: 16,
    paddingBottom: 24,
    gap: 8,
  },
  micStatusPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    justifyContent: 'center',
  },
  longPressHint: {
    fontSize: 10,
    color: C.dim,
    textAlign: 'center',
    letterSpacing: 0.8,
  },

  /* Expand toggle */
  expandToggle: {
    alignSelf: 'center',
    paddingVertical: 4,
  },
  expandText: {
    fontSize: 12,
    color: C.dim,
    letterSpacing: 0.5,
  },

  /* Command bar */
  commandBar: {
    gap: 8,
  },
  promptRow: {
    gap: 8,
    paddingHorizontal: 2,
  },
  promptChip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 14,
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
    borderWidth: 1,
    borderColor: C.border,
  },
  promptChipText: {
    fontSize: 12,
    color: C.textSec,
  },
  inputRow: {
    flexDirection: 'row',
    gap: 8,
  },
  textInput: {
    flex: 1,
    paddingHorizontal: 14,
    paddingVertical: 11,
    borderRadius: 16,
    backgroundColor: 'rgba(15, 23, 42, 0.7)',
    borderWidth: 1,
    borderColor: C.border,
    color: C.text,
    fontSize: 14,
  },
  sendBtn: {
    paddingHorizontal: 18,
    justifyContent: 'center',
    borderRadius: 16,
    backgroundColor: 'rgba(34, 211, 238, 0.15)',
    borderWidth: 1,
    borderColor: C.cyanBorder,
  },
  sendBtnDisabled: {
    opacity: 0.35,
  },
  sendBtnText: {
    fontSize: 14,
    fontWeight: '700',
    color: C.cyan,
  },
});
