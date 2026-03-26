/* ══════════════════════════════════════════════════════════════
   Axon — Voice Module
   ══════════════════════════════════════════════════════════════ */

function axonVoiceMixin() {
  return {

    // ── New state ──
    voiceMode: false,

    // ── Computed-like helpers ──
    azureSpeechConfigured() {
      return !!(this.settingsForm.azure_speech_key || this.settingsForm._azureSpeechKeyHint);
    },

    speechLocale() {
      const voice = this.settingsForm.azure_voice || 'en-ZA-LeahNeural';
      const match = String(voice).match(/^[a-z]{2}-[A-Z]{2}/);
      return match ? match[0] : 'en-ZA';
    },

    refreshVoiceCapability() {
      const hasBrowserRecognition = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
      const hasAzureSdk = !!window.SpeechSDK;
      this.speechInputSupported = hasBrowserRecognition || (hasAzureSdk && this.azureSpeechConfigured());
      this.speechOutputSupported = !!window.speechSynthesis || this.azureSpeechConfigured();
      this.speechSupported = this.speechInputSupported || this.speechOutputSupported;
    },

    voiceInputAvailable() {
      return !!this.speechInputSupported;
    },

    voiceOutputAvailable() {
      return !!this.speechOutputSupported;
    },

    // ── Voice input ──
    async startVoice() {
      if (this.voiceActive && this._speechRecognizer) {
        try {
          if (typeof this._speechRecognizer.stop === 'function') this._speechRecognizer.stop();
          if (typeof this._speechRecognizer.close === 'function') this._speechRecognizer.close();
        } catch (_) {}
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.showToast('Voice capture stopped');
        return;
      }
      const SpeechRec = window.webkitSpeechRecognition || window.SpeechRecognition;
      const isTrustedLocal = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
      if (!isTrustedLocal && !window.isSecureContext) {
        this.showToast('Voice input needs HTTPS or localhost');
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.showToast('Microphone capture is not available in this browser');
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach(track => track.stop());
      } catch (e) {
        const name = String(e?.name || '').toLowerCase();
        if (name.includes('notallowed') || name.includes('permission')) {
          this.showToast('Microphone access was blocked');
        } else {
          this.showToast('Could not access the microphone');
        }
        return;
      }
      if (!SpeechRec && window.SpeechSDK && this.azureSpeechConfigured()) {
        await this.startAzureVoiceRecognition();
        return;
      }
      if (!SpeechRec) {
        this.showToast('This browser does not expose live speech recognition here');
        return;
      }
      const recog = new SpeechRec();
      this._speechRecognizer = recog;
      recog.lang = this.speechLocale();
      recog.interimResults = false;
      recog.maxAlternatives = 1;
      if ('continuous' in recog) recog.continuous = false;
      this.voiceActive = true;
      recog.onresult = (e) => {
        const transcript = e?.results?.[0]?.[0]?.transcript || '';
        if (!transcript.trim()) {
          this.showToast('No speech was detected');
        } else if (this.chatInput.trim()) {
          this.chatInput = `${this.chatInput.trim()} ${transcript}`.trim();
        } else {
          this.chatInput = transcript;
        }
        this.resetChatComposerHeight();
        this.voiceActive = false;
        this._speechRecognizer = null;
      };
      recog.onerror = (event) => {
        this.voiceActive = false;
        this._speechRecognizer = null;
        const code = String(event?.error || '').toLowerCase();
        if (code === 'not-allowed' || code === 'service-not-allowed') {
          this.showToast('Microphone permission was denied');
        } else if (code === 'network') {
          this.showToast('Speech recognition network error');
        } else if (code === 'no-speech') {
          this.showToast('No speech detected');
        } else if (code === 'audio-capture') {
          this.showToast('No microphone was found');
        } else {
          this.showToast(code ? `Voice input failed: ${code}` : 'Voice input failed');
        }
      };
      recog.onend = () => {
        this.voiceActive = false;
        this._speechRecognizer = null;
      };
      try {
        recog.start();
      } catch (e) {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.showToast(`Voice input could not start: ${e.message || e}`);
      }
    },

    async startAzureVoiceRecognition() {
      try {
        const cfg = await this.api('GET', '/api/stt/token');
        if (!window.SpeechSDK) {
          this.showToast('Azure Speech SDK is still loading');
          return;
        }
        const sdk = window.SpeechSDK;
        const speechConfig = sdk.SpeechConfig.fromAuthorizationToken(cfg.token, cfg.region);
        speechConfig.speechRecognitionLanguage = this.speechLocale();
        const audioConfig = sdk.AudioConfig.fromDefaultMicrophoneInput();
        const recognizer = new sdk.SpeechRecognizer(speechConfig, audioConfig);
        this._speechRecognizer = recognizer;
        this.voiceActive = true;
        recognizer.recognizeOnceAsync(
          (result) => {
            const text = String(result?.text || '').trim();
            if (!text) {
              this.showToast('No speech was detected');
            } else if (this.chatInput.trim()) {
              this.chatInput = `${this.chatInput.trim()} ${text}`.trim();
            } else {
              this.chatInput = text;
            }
            this.resetChatComposerHeight();
            try { recognizer.close(); } catch (_) {}
            this.voiceActive = false;
            this._speechRecognizer = null;
          },
          (err) => {
            try { recognizer.close(); } catch (_) {}
            this.voiceActive = false;
            this._speechRecognizer = null;
            const message = typeof err === 'string' ? err : (err?.message || err?.errorDetails || '');
            this.showToast(message ? `Azure voice failed: ${message}` : 'Azure voice input failed');
          },
        );
      } catch (e) {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.showToast(`Azure voice unavailable: ${e.message || e}`);
      }
    },

    // ── Speech output helpers ──
    _cleanForSpeech(text) {
      return text
        .replace(/```[\s\S]*?```/g, 'code block.')       // fenced code blocks
        .replace(/`[^`]+`/g, '')                          // inline code
        .replace(/^#{1,6}\s+/gm, '')                      // headings
        .replace(/\*\*([^*]+)\*\*/g, '$1')                // bold
        .replace(/\*([^*]+)\*/g, '$1')                    // italic
        .replace(/__([^_]+)__/g, '$1')                    // bold underscore
        .replace(/_([^_]+)_/g, '$1')                      // italic underscore
        .replace(/~~([^~]+)~~/g, '$1')                    // strikethrough
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')          // links → label only
        .replace(/^[-*+]\s+/gm, '')                       // unordered list items
        .replace(/^\d+\.\s+/gm, '')                       // ordered list items
        .replace(/^>\s+/gm, '')                           // blockquotes
        .replace(/^---+$/gm, '')                          // horizontal rules
        .replace(/[|\\]/g, ' ')                           // table pipes
        .replace(/\n{3,}/g, '\n\n')                       // collapse blank lines
        .trim()
        .substring(0, 3000);
    },

    stopSpeech() {
      if (this._currentAudio) {
        this._currentAudio.pause();
        this._currentAudio.src = '';
        this._currentAudio = null;
      }
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    },

    async speakMessage(text) {
      this.stopSpeech();
      const clean = this._cleanForSpeech(text);
      // Try Azure TTS if configured
      if (this.azureSpeechConfigured() && this.settingsForm.azure_speech_region) {
        try {
          const res = await fetch('/api/tts', {
            method: 'POST',
            headers: this.authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
              text: clean,
              voice: this.settingsForm.azure_voice || 'en-ZA-LeahNeural',
              region: this.settingsForm.azure_speech_region,
            }),
          });
          if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            this._currentAudio = audio;
            audio.onended = () => { URL.revokeObjectURL(url); this._currentAudio = null; };
            audio.play();
            return;
          }
        } catch(e) { /* fall through to browser TTS */ }
      }
      // Browser TTS fallback
      if (!window.speechSynthesis) return;
      const utt = new SpeechSynthesisUtterance(clean);
      utt.lang = 'en-ZA';
      utt.rate = 1.05;
      window.speechSynthesis.speak(utt);
    },

    // ── New: voice mode toggle ──
    toggleVoiceMode() {
      this.voiceMode = !this.voiceMode;
      this.showToast(this.voiceMode ? 'Voice mode ON — responses will be spoken' : 'Voice mode OFF');
    },

    // ── New: orb state derivation ──
    orbState() {
      if (this.voiceActive) return 'listening';
      if (this._currentAudio) return 'speaking';
      if (this.chatLoading) return 'thinking';
      if (this.agentMode) return 'agent';
      return 'idle';
    },

    // ── New: auto-speak for voice mode ──
    autoSpeakResponse(text) {
      if (this.voiceMode && this.speechOutputSupported) {
        this.speakMessage(text);
      }
    },

  };
}

window.axonVoiceMixin = axonVoiceMixin;
