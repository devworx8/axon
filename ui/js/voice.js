/* ══════════════════════════════════════════════════════════════
   Axon — Voice Module
   ══════════════════════════════════════════════════════════════ */

function axonVoiceMixin() {
  return {

    // ── New state ──
    voiceMode: true,
    voiceStatus: {
      available: false,
      preferred_mode: 'browser',
      transcription_available: false,
      synthesis_available: false,
      detail: '',
      state: {},
    },

    // ── Computed-like helpers ──
    azureSpeechConfigured() {
      return !!(this.settingsForm.azure_speech_key || this.settingsForm._azureSpeechKeyHint);
    },

    speechLocale() {
      const voice = this.settingsForm.azure_voice || 'en-GB-RyanNeural';
      const match = String(voice).match(/^[a-z]{2}-[A-Z]{2}/);
      return match ? match[0] : 'en-GB';
    },

    refreshVoiceCapability() {
      const hasBrowserRecognition = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;
      const hasAzureSdk = !!window.SpeechSDK;
      this.speechInputSupported = hasBrowserRecognition || (hasAzureSdk && this.azureSpeechConfigured());
      this.speechOutputSupported = !!window.speechSynthesis || this.azureSpeechConfigured();
      this.speechSupported = this.speechInputSupported || this.speechOutputSupported;
    },

    async loadVoiceStatus(force = false) {
      if (!force && this.voiceStatus?.detail) return this.voiceStatus;
      try {
        const status = await this.api('GET', '/api/voice/status');
        this.voiceStatus = status || this.voiceStatus;
      } catch (e) {
        this.voiceStatus = {
          available: false,
          preferred_mode: 'browser',
          transcription_available: false,
          synthesis_available: false,
          detail: e?.message || 'Voice status unavailable',
          state: {},
        };
      }
      this.refreshVoiceCapability();
      return this.voiceStatus;
    },

    voiceInputAvailable() {
      return !!this.speechInputSupported;
    },

    voiceOutputAvailable() {
      return !!this.speechOutputSupported;
    },

    composerPrimaryAction() {
      if (this.chatLoading) return 'stop';
      if (String(this.chatInput || '').trim()) return 'send';
      return this.voiceInputAvailable() ? 'voice' : 'send';
    },

    async handleComposerPrimaryAction() {
      const action = this.composerPrimaryAction();
      if (action === 'voice') {
        this.openVoiceCommandCenter();
        return;
      }
      if (action === 'send') {
        await this.sendChat();
      }
    },

    latestAssistantMessage() {
      const messages = Array.isArray(this.chatMessages) ? this.chatMessages : [];
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message?.role === 'assistant') return message;
      }
      return null;
    },

    latestAssistantResponsePreview(limit = 800) {
      const message = this.latestAssistantMessage();
      const content = String(message?.content || '').trim();
      return content ? content.substring(0, limit) : '';
    },

    openVoiceCommandCenter() {
      this.showVoiceOrb = true;
      this.switchTab('chat');
      this.refreshVoiceCapability();
      this.ensureVoiceConversationState?.();
      if (this.chatInput && !this.voiceTranscript) {
        this.voiceTranscript = this.chatInput;
      }
      if (window.axonVoiceBootSound) {
        window.axonVoiceBootSound.play();
      }
      this._scheduleBootGreeting?.();
      this.syncVoiceCommandCenterRuntime?.();
    },

    closeVoiceCommandCenter(stopCapture = true) {
      this.showVoiceOrb = false;
      this.closeVoiceConversationRuntime?.();
      if (stopCapture && this.voiceActive) {
        this.startVoice();
      }
    },

    syncVoiceTranscript(text = '') {
      const value = String(text || '').trim();
      this.voiceTranscript = value;
      this.chatInput = value;
      this.resetChatComposerHeight();
    },

    clearVoiceTranscript() {
      this.voiceTranscript = '';
      this.chatInput = '';
      this.resetChatComposerHeight();
    },

    async sendVoiceCommand(commandText = '') {
      const text = String(commandText || this.voiceTranscript || this.chatInput || '').trim();
      const workspaceBusy = typeof this.currentWorkspaceRunActive === 'function'
        ? this.currentWorkspaceRunActive()
        : !!this.chatLoading;
      if (!text || workspaceBusy) return;
      this.onVoiceCommandDispatched?.(text);
      if (this.voiceActive) {
        this.startVoice();
      }
      this.chatInput = text;
      this.voiceTranscript = text;
      await this.sendChat();
      this.voiceTranscript = '';
    },

    voiceCenterStatusLabel() {
      const conversationLabel = this.voiceConversationStatusLabel?.();
      if (conversationLabel) return conversationLabel;
      if (this.reactorAsleep) return 'Reactor sleeping';
      const state = this.orbState();
      if (state === 'listening') return 'Listening for a command';
      if (state === 'speaking') return 'Speaking the result';
      if (state === 'thinking') return 'Processing your request';
      if (state === 'agent') return 'Agent mode ready';
      return this.voiceInputAvailable() ? 'Tap the orb to speak' : 'Voice input unavailable here';
    },

    voiceCenterStatusDetail() {
      const conversationDetail = this.voiceConversationStatusDetail?.();
      if (conversationDetail) return conversationDetail;
      if (this.voiceActive) return 'Axon is capturing your voice and updating the command live.';
      if (this.chatLoading) return this.liveOperator?.detail || 'Axon is working through the latest command.';
      if (this.voiceTranscript) return 'Review the transcript, then send it or keep dictating.';
      return this.voiceOutputAvailable() ? 'Voice replies can be spoken automatically when Auto-speak is on.' : 'Configure browser or Azure speech to enable spoken replies.';
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
      recog.interimResults = true;
      recog.maxAlternatives = 1;
      if ('continuous' in recog) recog.continuous = false;
      this.voiceSessionStartedAt = new Date().toISOString();
      this.voiceActive = true;
      recog.onresult = (e) => {
        let finalTranscript = '';
        let interimTranscript = '';
        for (let idx = e.resultIndex || 0; idx < (e.results?.length || 0); idx += 1) {
          const result = e.results[idx];
          const transcript = result?.[0]?.transcript || '';
          if (result?.isFinal) finalTranscript += `${transcript} `;
          else interimTranscript += `${transcript} `;
        }
        const combined = `${finalTranscript}${interimTranscript}`.trim();
        if (!combined) {
          this.showToast('No speech was detected');
        } else {
          this.syncVoiceTranscript(combined);
        }
        if (finalTranscript.trim() && !interimTranscript.trim()) {
          this.voiceActive = false;
          this._speechRecognizer = null;
        }
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
        this.voiceSessionStartedAt = new Date().toISOString();
        this.voiceActive = true;
        recognizer.recognizeOnceAsync(
          (result) => {
            const text = String(result?.text || '').trim();
            if (!text) {
              this.showToast('No speech was detected');
            } else {
              this.syncVoiceTranscript(text);
            }
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

  };
}

window.axonVoiceMixin = axonVoiceMixin;
