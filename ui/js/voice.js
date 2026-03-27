/* ══════════════════════════════════════════════════════════════
   Axon — Voice Module
   ══════════════════════════════════════════════════════════════ */

function axonVoiceMixin() {
  return {
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
      const recognitionSupported = hasBrowserRecognition || (hasAzureSdk && this.azureSpeechConfigured());
      const synthesisSupported = !!window.speechSynthesis || this.azureSpeechConfigured();
      if (this.voice?.supported) {
        this.voice.supported.recognition = recognitionSupported;
        this.voice.supported.synthesis = synthesisSupported;
      }
      this.speechInputSupported = recognitionSupported;
      this.speechOutputSupported = synthesisSupported;
      this.speechSupported = this.speechInputSupported || this.speechOutputSupported;
    },

    async loadVoiceStatus(force = false) {
      if (this.voice.statusLoading && !force) return;
      this.voice.statusLoading = true;
      try {
        const resp = await fetch('/api/voice/status', {
          headers: this.authHeaders(),
          cache: 'no-store',
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          throw new Error('Session expired');
        }
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || 'Voice status unavailable');
        this.voice.server = data;
        if (data.preferred_mode) {
          this.voice.mode = data.preferred_mode;
        }
      } catch (e) {
        this.voice.server = {
          available: false,
          preferred_mode: 'browser',
          transcription_available: false,
          synthesis_available: false,
          detail: e.message || 'Voice status unavailable',
        };
      }
      this.voice.statusLoading = false;
    },

    voiceInputAvailable() {
      return !!(
        this.voice?.supported?.recognition
        || this.speechInputSupported
        || (this.voice?.server?.transcription_available && typeof MediaRecorder !== 'undefined')
      );
    },

    voiceOutputAvailable() {
      return !!(
        this.voice?.supported?.synthesis
        || this.speechOutputSupported
        || this.voice?.server?.synthesis_available
      );
    },

    composerPrimaryAction() {
      if (this.chatLoading) return 'stop';
      if (String(this.chatInput || '').trim()) return 'send';
      return this.voiceInputAvailable() ? 'voice' : 'send';
    },

    async handleComposerPrimaryAction() {
      const action = this.composerPrimaryAction();
      if (action === 'voice') {
        this.openVoiceCommandCenter(true);
        return;
      }
      if (action === 'send') {
        await this.sendChat();
      }
    },

    toggleVoiceMode(force = null) {
      const next = typeof force === 'boolean' ? force : !this.voice.open;
      this.voice.open = next;
      this.voice.enabled = next;
      this.showVoiceOrb = next;
      this.voice.wakeLocked = next;
      if (next) {
        this.playVoiceTone('wake');
      }
      if (!next) {
        this._voiceStopRequested = true;
        try {
          if (typeof this._speechRecognizer?.stop === 'function') this._speechRecognizer.stop();
          if (typeof this._speechRecognizer?.close === 'function') this._speechRecognizer.close();
        } catch (_) {}
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.voiceActive = false;
        this.stopMicAnalyzer();
        this.stopSpeech();
        this.playVoiceTone('close');
      }
      this.setVoiceState('idle');
    },

    setVoiceState(state) {
      this.voice.state = String(state || 'idle');
    },

    voiceVisualState() {
      const state = String(this.voice?.state || 'idle');
      if (['idle', 'listening', 'thinking', 'speaking'].includes(state)) return state;
      return 'idle';
    },

    voiceStateCaption() {
      const state = String(this.voice?.state || 'idle');
      if (state === 'listening') return 'Triangle listening • command intake open';
      if (state === 'thinking') return 'Triangle processing • routing through Axon';
      if (state === 'speaking') return 'Triangle open • core engaged';
      return 'Triangle sealed • orb hidden inside';
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

    voiceDisplayTranscript() {
      const transcript = String(this.voice?.transcript || '').trim();
      if (transcript) return transcript;
      if (this.voice?.state === 'listening') return 'Listening for your command...';
      return 'Tap Speak to start the voice loop.';
    },

    voiceDisplayResponse() {
      const response = String(this.voice?.responseText || '').trim();
      if (response) return response;
      const preview = String(this.latestAssistantResponsePreview() || '').trim();
      if (preview) return preview;
      if (this.voice?.state === 'thinking') return 'Axon is reasoning through the command.';
      return 'Axon will speak the next assistant response here.';
    },

    voiceStatusLabel() {
      const state = this.voiceVisualState();
      if (state === 'listening') return 'LISTENING';
      if (state === 'thinking') return 'THINKING';
      if (state === 'speaking') return 'SPEAKING';
      return 'IDLE';
    },

    voiceStatusHint() {
      const state = this.voiceVisualState();
      if (state === 'listening') return 'Mic live • transcript streaming';
      if (state === 'thinking') return 'Mic closed • Axon reasoning';
      if (state === 'speaking') return 'Response channel active';
      return 'Triangle sealed • awaiting wake';
    },

    normalizedVoiceLevel() {
      const raw = Number(this.voice?.level || 0);
      if (!Number.isFinite(raw)) return 0;
      return Math.max(0, Math.min(1, raw));
    },

    voiceCanUseLocalTranscription() {
      return this.voice.mode === 'local' && !!this.voice.server?.transcription_available && typeof MediaRecorder !== 'undefined';
    },

    voiceCanUseLocalSynthesis() {
      return this.voice.mode === 'local' && !!this.voice.server?.synthesis_available;
    },

    voiceGlowStyle() {
      const intensity = this.normalizedVoiceLevel();
      const base = this.voiceVisualState() === 'idle' ? 0.12 : 0.28;
      const opacity = Math.min(1, base + intensity * 0.75);
      const scale = 0.74 + intensity * 0.42;
      const blur = 16 + intensity * 52;
      return `opacity:${opacity}; transform: translate(-50%, -50%) scale(${scale}); filter: drop-shadow(0 0 ${blur}px rgba(68,232,255,.78));`;
    },

    voiceBeamStyle(multiplier = 1) {
      const intensity = this.normalizedVoiceLevel();
      const opacity = 0.12 + intensity * 0.88 * multiplier;
      const scaleX = 0.86 + intensity * 0.28;
      return `opacity:${Math.min(1, opacity)}; transform: translate(-50%, -50%) scaleX(${scaleX});`;
    },

    voiceRingStyle(index = 0) {
      const intensity = this.normalizedVoiceLevel();
      const scale = 0.94 + index * 0.16 + intensity * 0.32;
      const opacity = Math.max(0.08, 0.24 - index * 0.06 + intensity * 0.24);
      return `opacity:${Math.min(0.9, opacity)}; transform: translate(-50%, -50%) scale(${scale});`;
    },

    async initMicAnalyzer() {
      if (this.voice.stream && this.voice.analyser) return;
      if (!navigator.mediaDevices?.getUserMedia) return;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.82;
      source.connect(analyser);
      this.voice.audioContext = audioContext;
      this.voice.stream = stream;
      this.voice.sourceNode = source;
      this.voice.analyser = analyser;
      this.voice.dataArray = new Uint8Array(analyser.frequencyBinCount);
      this.voice.analysisSource = 'mic';
      this.startVoiceLevelLoop('mic');
    },

    voiceRecorderMimeType() {
      const candidates = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/ogg',
      ];
      return candidates.find(type => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(type)) || '';
    },

    async uploadVoiceBlobForTranscription(blob) {
      const form = new FormData();
      form.append('file', blob, blob.type.includes('ogg') ? 'voice.ogg' : 'voice.webm');
      const language = this.voice.server?.language || 'en';
      const resp = await fetch(`/api/voice/transcribe?language=${encodeURIComponent(language)}`, {
        method: 'POST',
        headers: this.authHeaders(),
        body: form,
      });
      if (resp.status === 401) {
        this.handleAuthRequired();
        throw new Error('Session expired');
      }
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Transcription failed');
      return data;
    },

    async startLocalVoiceCapture() {
      if (this.voice.recording && this.voice.mediaRecorder) {
        this.voice.mediaRecorder.stop();
        return;
      }
      await this.initMicAnalyzer();
      if (!this.voice.stream) {
        throw new Error('Microphone stream unavailable');
      }
      this.stopSpeech();
      this._voiceStopRequested = false;
      this.voice.recordedChunks = [];
      const mimeType = this.voiceRecorderMimeType();
      const recorder = mimeType ? new MediaRecorder(this.voice.stream, { mimeType }) : new MediaRecorder(this.voice.stream);
      this.voice.mediaRecorder = recorder;
      recorder.onstart = () => {
        this.voice.recording = true;
        this.voiceActive = true;
        this.voice.responseText = '';
        this.syncVoiceTranscript('');
        this.setVoiceState('listening');
      };
      recorder.ondataavailable = (event) => {
        if (event.data?.size) this.voice.recordedChunks.push(event.data);
      };
      recorder.onerror = (event) => {
        this.voice.recording = false;
        this.voiceActive = false;
        this.voice.mediaRecorder = null;
        this.stopMicAnalyzer();
        this.setVoiceState('idle');
        this.showToast(`Voice capture failed: ${event?.error?.message || 'recording error'}`);
      };
      recorder.onstop = async () => {
        this.voice.recording = false;
        this.voiceActive = false;
        this.voice.mediaRecorder = null;
        const chunks = [...(this.voice.recordedChunks || [])];
        this.voice.recordedChunks = [];
        this.stopMicAnalyzer();
        if (this._voiceStopRequested) {
          this._voiceStopRequested = false;
          this.setVoiceState('idle');
          return;
        }
        if (!chunks.length) {
          this.setVoiceState('idle');
          return;
        }
        this.setVoiceState('thinking');
        try {
          const mime = mimeType || 'audio/webm';
          const blob = new Blob(chunks, { type: mime });
          const result = await this.uploadVoiceBlobForTranscription(blob);
          const text = String(result?.text || '').trim();
          this.syncVoiceTranscript(text);
          if (!text) {
            this.setVoiceState('idle');
            this.showToast('No speech was detected');
            return;
          }
          await this.executeVoiceCommand();
        } catch (e) {
          this.setVoiceState('idle');
          this.showToast(`Local transcription failed: ${e.message || e}`);
          await this.loadVoiceStatus(true);
        }
      };
      recorder.start();
    },

    stopMicAnalyzer() {
      if (this.voice.analysisSource === 'mic') {
        this.stopVoiceLevelLoop();
      }
      try { this.voice.sourceNode?.disconnect?.(); } catch (_) {}
      try { this.voice.analyser?.disconnect?.(); } catch (_) {}
      try { this.voice.stream?.getTracks?.().forEach(track => track.stop()); } catch (_) {}
      if (this.voice.audioContext && this.voice.analysisSource === 'mic') {
        try { this.voice.audioContext.close(); } catch (_) {}
      }
      this.voice.stream = null;
      this.voice.sourceNode = null;
      this.voice.analyser = null;
      this.voice.dataArray = null;
      if (this.voice.analysisSource === 'mic') {
        this.voice.audioContext = null;
        this.voice.analysisSource = '';
        this.voice.level = 0;
      }
    },

    attachPlaybackAnalyzer(audio) {
      if (!audio) return;
      if (!window.AudioContext && !window.webkitAudioContext) return;
      if (this.voice.analysisSource === 'playback') {
        this.stopPlaybackAnalyzer();
      }
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaElementSource(audio);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyser.connect(audioContext.destination);
      this.voice.playbackAudioContext = audioContext;
      this.voice.playbackSourceNode = source;
      this.voice.playbackAnalyser = analyser;
      this.voice.playbackDataArray = new Uint8Array(analyser.frequencyBinCount);
      this.voice.analysisSource = 'playback';
      this.startVoiceLevelLoop('playback');
    },

    stopPlaybackAnalyzer() {
      if (this.voice.analysisSource === 'playback') {
        this.stopVoiceLevelLoop();
      }
      try { this.voice.playbackSourceNode?.disconnect?.(); } catch (_) {}
      try { this.voice.playbackAnalyser?.disconnect?.(); } catch (_) {}
      if (this.voice.playbackAudioContext) {
        try { this.voice.playbackAudioContext.close(); } catch (_) {}
      }
      this.voice.playbackAudioContext = null;
      this.voice.playbackSourceNode = null;
      this.voice.playbackAnalyser = null;
      this.voice.playbackDataArray = null;
      if (this.voice.analysisSource === 'playback') {
        this.voice.analysisSource = '';
        this.voice.level = 0;
      }
    },

    startVoiceLevelLoop(source = 'mic') {
      this.stopVoiceLevelLoop();
      const update = () => {
        const analyser = source === 'playback' ? this.voice.playbackAnalyser : this.voice.analyser;
        const dataArray = source === 'playback' ? this.voice.playbackDataArray : this.voice.dataArray;
        if (!analyser || !dataArray) {
          this.voice.level = 0;
          return;
        }
        analyser.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((sum, value) => sum + value, 0) / dataArray.length;
        const normalized = Math.max(0, Math.min(1, average / 255));
        const current = Number(this.voice.level || 0);
        this.voice.level = current * 0.55 + normalized * 0.45;
        this.voice.levelRaf = requestAnimationFrame(update);
      };
      this.voice.levelRaf = requestAnimationFrame(update);
    },

    stopVoiceLevelLoop() {
      if (this.voice.levelRaf) {
        cancelAnimationFrame(this.voice.levelRaf);
        this.voice.levelRaf = null;
      }
    },

    playVoiceTone(kind = 'wake') {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const context = new AudioCtx();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.connect(gain);
      gain.connect(context.destination);
      const now = context.currentTime;
      const tones = {
        wake: { start: 520, end: 720, duration: 0.12, gain: 0.018 },
        confirm: { start: 720, end: 980, duration: 0.1, gain: 0.016 },
        close: { start: 440, end: 300, duration: 0.14, gain: 0.014 },
      };
      const preset = tones[kind] || tones.wake;
      oscillator.type = kind === 'close' ? 'sine' : 'triangle';
      oscillator.frequency.setValueAtTime(preset.start, now);
      oscillator.frequency.exponentialRampToValueAtTime(Math.max(120, preset.end), now + preset.duration);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(preset.gain, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + preset.duration);
      oscillator.start(now);
      oscillator.stop(now + preset.duration + 0.02);
      oscillator.onended = () => {
        try { context.close(); } catch (_) {}
      };
    },

    openVoiceCommandCenter(autoListen = false) {
      this.toggleVoiceMode(true);
      this.activeTab = 'chat';
      this.refreshVoiceCapability();
      if (this.chatInput && !this.voice.transcript) {
        this.syncVoiceTranscript(this.chatInput);
      }
      if (autoListen) {
        this.startVoiceListening();
      }
    },

    closeVoiceCommandCenter(stopCapture = true) {
      if (stopCapture) {
        this._voiceStopRequested = true;
        try {
          if (typeof this._speechRecognizer?.stop === 'function') this._speechRecognizer.stop();
          if (typeof this._speechRecognizer?.close === 'function') this._speechRecognizer.close();
        } catch (_) {}
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.voiceActive = false;
        this.stopMicAnalyzer();
        this.stopSpeech();
      }
      this.toggleVoiceMode(false);
    },

    syncVoiceTranscript(text = '') {
      const value = String(text || '').trim();
      this.voice.transcript = value;
      this.voiceTranscript = value;
      this.chatInput = value;
      this.resetChatComposerHeight();
    },

    clearVoiceTranscript() {
      this.voice.transcript = '';
      this.voice.responseText = '';
      this.voice.level = 0;
      this.voiceTranscript = '';
      this.chatInput = '';
      this.resetChatComposerHeight();
      this.setVoiceState('idle');
    },

    async sendVoiceCommand() {
      const text = String(this.voice.transcript || this.voiceTranscript || this.chatInput || '').trim();
      if (!text || this.chatLoading) return;
      this.syncVoiceTranscript(text);
      await this.executeVoiceCommand();
    },

    async executeVoiceCommand() {
      const text = String(this.voice.transcript || this.chatInput || '').trim();
      if (!text || this.chatLoading) {
        this.setVoiceState('idle');
        return;
      }
      this.voice.responseText = '';
      this.setVoiceState('thinking');
      this.chatInput = text;
      await this.sendChat();
      const reply = this.latestAssistantMessage()?.content || 'Done';
      this.voice.responseText = reply;
      await this.speakVoiceResponse(reply);
    },

    // ── Voice input ──
    async startVoice() {
      return this.startVoiceListening();
    },

    async startVoiceListening() {
      if (this.voiceCanUseLocalTranscription()) {
        try {
          await this.startLocalVoiceCapture();
        } catch (e) {
          this.showToast(e.message || 'Local voice capture unavailable');
        }
        return;
      }
      if (this.voiceActive && this._speechRecognizer) {
        this._voiceStopRequested = true;
        try {
          if (typeof this._speechRecognizer.stop === 'function') this._speechRecognizer.stop();
          if (typeof this._speechRecognizer.close === 'function') this._speechRecognizer.close();
        } catch (_) {}
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.stopMicAnalyzer();
        this.setVoiceState('idle');
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
        await this.initMicAnalyzer();
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
        this.showToast('Speech not supported in this browser');
        return;
      }
      this.stopSpeech();
      this._voiceStopRequested = false;
      const recog = new SpeechRec();
      this._speechRecognizer = recog;
      this.voiceRecognition = recog;
      recog.lang = this.speechLocale();
      recog.interimResults = true;
      recog.maxAlternatives = 1;
      if ('continuous' in recog) recog.continuous = false;
      recog.onstart = () => {
        this.voiceSessionStartedAt = new Date().toISOString();
        this.voiceActive = true;
        this.voice.responseText = '';
        this.syncVoiceTranscript('');
        this.setVoiceState('listening');
      };
      recog.onresult = (e) => {
        let text = '';
        for (let idx = e.resultIndex || 0; idx < (e.results?.length || 0); idx += 1) {
          const result = e.results[idx];
          text += result?.[0]?.transcript || '';
        }
        this.syncVoiceTranscript(text);
      };
      recog.onerror = (event) => {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.setVoiceState('idle');
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
      recog.onend = async () => {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.stopMicAnalyzer();
        if (this._voiceStopRequested) {
          this._voiceStopRequested = false;
          this.setVoiceState('idle');
          return;
        }
        if (!String(this.voice.transcript || '').trim()) {
          this.setVoiceState('idle');
          return;
        }
        await this.executeVoiceCommand();
      };
      try {
        recog.start();
      } catch (e) {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.stopMicAnalyzer();
        this.setVoiceState('idle');
        this.showToast(`Voice input could not start: ${e.message || e}`);
      }
    },

    async startAzureVoiceRecognition() {
      try {
        this.stopSpeech();
        this._voiceStopRequested = false;
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
        this.voiceRecognition = recognizer;
        this.voiceSessionStartedAt = new Date().toISOString();
        this.voiceActive = true;
        this.voice.responseText = '';
        this.syncVoiceTranscript('');
        this.setVoiceState('listening');
        recognizer.recognizeOnceAsync(
          async (result) => {
            const text = String(result?.text || '').trim();
            this.syncVoiceTranscript(text);
            try { recognizer.close(); } catch (_) {}
            this.voiceActive = false;
            this._speechRecognizer = null;
            this.voiceRecognition = null;
            this.stopMicAnalyzer();
            if (!text) {
              this.setVoiceState('idle');
              this.showToast('No speech was detected');
              return;
            }
            await this.executeVoiceCommand();
          },
          (err) => {
            try { recognizer.close(); } catch (_) {}
            this.voiceActive = false;
            this._speechRecognizer = null;
            this.voiceRecognition = null;
            this.stopMicAnalyzer();
            this.setVoiceState('idle');
            const message = typeof err === 'string' ? err : (err?.message || err?.errorDetails || '');
            this.showToast(message ? `Azure voice failed: ${message}` : 'Azure voice input failed');
          },
        );
      } catch (e) {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.voiceRecognition = null;
        this.stopMicAnalyzer();
        this.setVoiceState('idle');
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
      if (this.voice.recording && this.voice.mediaRecorder) {
        this._voiceStopRequested = true;
        try { this.voice.mediaRecorder.stop(); } catch (_) {}
      }
      if (this._currentAudio) {
        this._currentAudio.pause();
        this._currentAudio.src = '';
        this._currentAudio = null;
      }
      this.stopPlaybackAnalyzer();
      fetch('/api/voice/stop', {
        method: 'POST',
        headers: this.authHeaders({ 'Content-Type': 'application/json' }),
      }).catch(() => {});
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      if (this.voice?.open && this.voice.state === 'speaking') {
        this.setVoiceState('idle');
      }
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
            audio.crossOrigin = 'anonymous';
            this._currentAudio = audio;
            audio.onplay = () => this.attachPlaybackAnalyzer(audio);
            audio.onended = () => {
              URL.revokeObjectURL(url);
              this._currentAudio = null;
              this.stopPlaybackAnalyzer();
            };
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

    async speakVoiceResponse(text) {
      const clean = this._cleanForSpeech(text);
      this.voice.responseText = clean;
      if (!clean) {
        this.setVoiceState('idle');
        return;
      }
      this.stopSpeech();
      this.playVoiceTone('confirm');
      if (this.voiceCanUseLocalSynthesis()) {
        try {
          const resp = await fetch('/api/voice/speak', {
            method: 'POST',
            headers: this.authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ text: clean, format: 'wav' }),
          });
          if (resp.status === 401) {
            this.handleAuthRequired();
            throw new Error('Session expired');
          }
          if (!resp.ok) {
            const error = await resp.json().catch(() => ({}));
            throw new Error(error.detail || 'Local speech failed');
          }
          const blob = await resp.blob();
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          audio.crossOrigin = 'anonymous';
          this._currentAudio = audio;
          audio.onplay = () => {
            this.setVoiceState('speaking');
            this.attachPlaybackAnalyzer(audio);
          };
          audio.onended = () => {
            URL.revokeObjectURL(url);
            this._currentAudio = null;
            this.stopPlaybackAnalyzer();
            this.setVoiceState('idle');
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            this._currentAudio = null;
            this.stopPlaybackAnalyzer();
            this.setVoiceState('idle');
          };
          await audio.play();
          return;
        } catch (e) {
          this.showToast(`Local speech failed: ${e.message || e}`);
          await this.loadVoiceStatus(true);
        }
      }
      if (!window.speechSynthesis) {
        this.setVoiceState('speaking');
        await this.speakMessage(clean);
        this.setVoiceState('idle');
        return;
      }
      const utter = new SpeechSynthesisUtterance(clean);
      utter.lang = this.speechLocale();
      utter.rate = 1.02;
      utter.onstart = () => this.setVoiceState('speaking');
      utter.onend = () => this.setVoiceState('idle');
      utter.onerror = () => this.setVoiceState('idle');
      window.speechSynthesis.speak(utter);
    },

    // ── New: orb state derivation ──
    orbState() {
      const state = String(this.voice?.state || 'idle');
      if (['idle', 'listening', 'thinking', 'speaking'].includes(state)) return state;
      if (this.agentMode) return 'agent';
      return 'idle';
    },

    toggleVoiceAutoSpeak() {
      this.voiceAutoSpeak = !this.voiceAutoSpeak;
      this.showToast(this.voiceAutoSpeak ? 'Auto-speak enabled' : 'Auto-speak disabled');
    },

    // ── New: auto-speak for responses ──
    autoSpeakResponse(text) {
      if (this.voiceAutoSpeak && this.speechOutputSupported) {
        this.speakMessage(text);
      }
    },

  };
}

window.axonVoiceMixin = axonVoiceMixin;
