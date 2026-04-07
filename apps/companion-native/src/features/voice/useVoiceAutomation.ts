import { useEffect, useRef } from 'react';

type VoiceAutomationOptions = {
  active: boolean;
  enabled: boolean;
  autoListen: boolean;
  axonArmed: boolean;
  ready: boolean;
  checkingStatus: boolean;
  recording: boolean;
  transcribing: boolean;
  sending: boolean;
  speaking: boolean;
  approvalPending: boolean;
  captureError?: string | null;
  refreshVoiceStatus: () => Promise<unknown>;
  startRecording: () => Promise<void>;
};

function isBlockingCaptureError(message: string | null | undefined): boolean {
  const value = String(message || '').trim().toLowerCase();
  if (!value) {
    return false;
  }
  return (
    value.includes('permission')
    || value.includes('denied')
    || value.includes('disabled in settings')
  );
}

export function useVoiceAutomation({
  active,
  enabled,
  autoListen,
  axonArmed,
  ready,
  checkingStatus,
  recording,
  transcribing,
  sending,
  speaking,
  approvalPending,
  captureError,
  refreshVoiceStatus,
  startRecording,
}: VoiceAutomationOptions) {
  const startPendingRef = useRef(false);

  useEffect(() => {
    if (!active || !enabled || axonArmed) {
      return;
    }
    let cancelled = false;
    const refresh = async () => {
      try {
        await refreshVoiceStatus();
      } catch {
        // Keep polling quietly until Axon comes back online.
      }
    };
    refresh();
    const interval = setInterval(() => {
      if (cancelled) {
        return;
      }
      refresh().catch(() => undefined);
    }, ready ? 15000 : 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [active, axonArmed, enabled, ready, refreshVoiceStatus]);

  useEffect(() => {
    if (!active || !enabled || !autoListen || axonArmed) {
      return;
    }
    if (!ready || checkingStatus || recording || transcribing || sending || speaking || approvalPending) {
      return;
    }
    if (startPendingRef.current || isBlockingCaptureError(captureError)) {
      return;
    }
    const timer = setTimeout(() => {
      startPendingRef.current = true;
      startRecording()
        .catch(() => undefined)
        .finally(() => {
          startPendingRef.current = false;
        });
    }, 320);
    return () => clearTimeout(timer);
  }, [
    active,
    approvalPending,
    autoListen,
    axonArmed,
    captureError,
    checkingStatus,
    enabled,
    ready,
    recording,
    sending,
    speaking,
    startRecording,
    transcribing,
  ]);
}
