/* ══════════════════════════════════════════════════════════════
   Axon — Voice Auto-Capture (timer-based auto-stop + auto-listen)
   ══════════════════════════════════════════════════════════════
   Simple hands-free voice on mobile/PWA:
   - Auto-start recording when voice mode opens
   - Auto-stop after a fixed recording window (10s)
   - Transcribe, dispatch, re-arm — continuous loop
   No AudioContext / VAD — just a timer. Azure STT trims silence.
   ══════════════════════════════════════════════════════════════ */

const VOICE_AUTO_CAPTURE_MS = 10000; // record for 10 seconds then auto-send

function axonVoiceAutoCaptureMixin() {
  return {
    _voiceAutoStopTimer: 0,
    _voiceAutoListenTimer: 0,

    /** Start the auto-stop countdown after recording begins. */
    _initVoiceVAD(/* stream — kept for call-site compat */) {
      this._clearAutoStopTimer();
      this._voiceAutoStopTimer = setTimeout(
        () => this._onVoiceAutoTimeout(),
        VOICE_AUTO_CAPTURE_MS,
      );
    },

    /** Cancel the auto-stop countdown. */
    _destroyVoiceVAD() {
      this._clearAutoStopTimer();
    },

    _clearAutoStopTimer() {
      if (this._voiceAutoStopTimer) {
        clearTimeout(this._voiceAutoStopTimer);
        this._voiceAutoStopTimer = 0;
      }
    },

    /** Called when the recording window expires — stop, transcribe, dispatch. */
    async _onVoiceAutoTimeout() {
      this._voiceAutoStopTimer = 0;
      if (!this.voiceActive || !this._voiceRecorder) return;
      const transcript = await this.stopRecordedVoiceCapture?.();
      const text = String(transcript || this.voiceTranscript || '').trim();
      if (text) {
        await this.dispatchVoiceCommand?.(text);
      }
      // Re-arm for continuous hands-free loop
      if (this.showVoiceOrb && !this.reactorAsleep) {
        this._scheduleVoiceAutoListen();
      }
    },

    /** Auto-start listening shortly after voice mode opens on mobile. */
    _scheduleVoiceAutoListen() {
      clearTimeout(this._voiceAutoListenTimer);
      this._voiceAutoListenTimer = setTimeout(async () => {
        if (!this.showVoiceOrb || this.reactorAsleep || this.voiceActive) return;
        if (!this.isMobile && window.innerWidth >= 768 && !_isStandalonePWA()) return;
        if (this.chatLoading) return;
        try { await this.loadVoiceStatus?.(); } catch (_) {}
        if (this.voiceShouldUseRecordedCapture?.()) {
          await this.startVoice?.();
        }
      }, 1200);
    },

    /** Cleanup all timers. */
    _cleanupVoiceAutoCapture() {
      clearTimeout(this._voiceAutoListenTimer);
      this._clearAutoStopTimer();
    },
  };
}

function _isStandalonePWA() {
  return !!(
    window.matchMedia?.('(display-mode: standalone)')?.matches ||
    window.navigator?.standalone
  );
}

window.axonVoiceAutoCaptureMixin = axonVoiceAutoCaptureMixin;
