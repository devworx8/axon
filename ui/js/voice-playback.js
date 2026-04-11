/* ══════════════════════════════════════════════════════════════
   Axon — Voice Playback Module
   ══════════════════════════════════════════════════════════════ */

function axonVoicePlaybackMixin() {
  return {

    voiceSpeechBusy() {
      return !!(this._speechPlaybackPending || this._currentAudio || this._speechSynthActive);
    },

    voiceSpeechRate() {
      const raw = Number.parseFloat(this.settingsForm?.voice_speech_rate);
      if (!Number.isFinite(raw)) return 0.85;
      return Math.max(0.50, Math.min(1.15, raw));
    },

    voiceSpeechPitch() {
      const raw = Number.parseFloat(this.settingsForm?.voice_speech_pitch);
      if (!Number.isFinite(raw)) return 1.04;
      return Math.max(0.5, Math.min(1.5, raw));
    },

    _pickBestBrowserVoice() {
      const synthesis = window.speechSynthesis;
      if (!synthesis || typeof synthesis.getVoices !== 'function') return null;
      if (this._cachedBrowserVoice) return this._cachedBrowserVoice;
      const voices = synthesis.getVoices();
      if (!Array.isArray(voices) || !voices.length) return null;
      const prefs = [
        /microsoft.*david/i,
        /\bdaniel\b/i,
        /google.*uk.*english.*male/i,
        /google.*us.*english/i,
        /\bnatural\b/i,
        /\bneural\b/i,
        /\benhanced\b/i,
        /\bpremium\b/i,
      ];
      for (const pref of prefs) {
        const match = voices.find(v => pref.test(v.name));
        if (match) { this._cachedBrowserVoice = match; return match; }
      }
      const en = voices.find(v => v.lang?.startsWith('en') && v.localService === false)
        || voices.find(v => v.lang?.startsWith('en'));
      if (en) { this._cachedBrowserVoice = en; return en; }
      return voices[0];
    },

    _cleanForSpeech(text) {
      const helper = window.axonVoiceSpeech;
      if (helper && typeof helper.cleanText === 'function') {
        return helper.cleanText(text);
      }
      return String(text || '').trim();
    },

    _speechChunks(text, maxChunkLength = 420) {
      const helper = window.axonVoiceSpeech;
      if (helper && typeof helper.splitText === 'function') {
        return helper.splitText(text, maxChunkLength);
      }
      const clean = this._cleanForSpeech(text);
      return clean ? [clean] : [];
    },

    stopSpeech() {
      this._speechPlaybackSession = Number(this._speechPlaybackSession || 0) + 1;
      this._speechSynthActive = false;
      this._speechPlaybackPending = false;
      this._speechPlaybackKind = '';
      const abortController = this._speechPlaybackAbortController;
      this._speechPlaybackAbortController = null;
      if (abortController && typeof abortController.abort === 'function') {
        try { abortController.abort(); } catch (_) {}
      }
      const resolveCurrent = this._speechPlaybackResolveCurrent;
      this._speechPlaybackResolveCurrent = null;
      if (typeof resolveCurrent === 'function') {
        try { resolveCurrent(); } catch (_) {}
      }
      if (this._currentAudio) {
        this._currentAudio.pause();
        this._currentAudio.src = '';
        this._currentAudio = null;
      }
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    },

    async _playAudioChunk(audio, sessionId, cleanup = null) {
      return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (error = null) => {
          if (settled) return;
          settled = true;
          if (this._speechPlaybackResolveCurrent === finish) {
            this._speechPlaybackResolveCurrent = null;
          }
          if (this._currentAudio === audio) {
            this._currentAudio = null;
          }
          if (typeof cleanup === 'function') cleanup();
          if (sessionId !== this._speechPlaybackSession) {
            resolve();
            return;
          }
          if (error) reject(error);
          else resolve();
        };

        this._speechPlaybackResolveCurrent = finish;
        audio.onended = () => finish();
        audio.onerror = () => finish(new Error('Audio playback failed'));
        this._currentAudio = audio;

        try {
          const playResult = audio.play();
          if (playResult && typeof playResult.then === 'function') {
            playResult.catch((error) => finish(error));
          }
        } catch (error) {
          finish(error);
        }
      });
    },

    async _playAzureSpeechChunks(chunks, sessionId) {
      let playedChunks = 0;
      const abortController = typeof AbortController === 'function' ? new AbortController() : null;
      this._speechPlaybackAbortController = abortController;
      try {
        for (const chunk of chunks) {
          if (sessionId !== this._speechPlaybackSession || abortController?.signal?.aborted) return playedChunks;
          const res = await fetch('/api/tts', {
            method: 'POST',
            headers: this.authHeaders({ 'Content-Type': 'application/json' }),
            signal: abortController?.signal,
            body: JSON.stringify({
              text: chunk,
              voice: this.settingsForm.azure_voice || 'en-GB-RyanNeural',
              region: this.settingsForm.azure_speech_region,
              rate: this.voiceSpeechRate(),
              pitch: this.voiceSpeechPitch(),
            }),
          });
          if (sessionId !== this._speechPlaybackSession || abortController?.signal?.aborted) return playedChunks;
          if (!res.ok) {
            throw new Error(`Azure TTS failed (${res.status})`);
          }
          const blob = await res.blob();
          if (sessionId !== this._speechPlaybackSession || abortController?.signal?.aborted) return playedChunks;
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          await this._playAudioChunk(audio, sessionId, () => URL.revokeObjectURL(url));
          playedChunks += 1;
        }
        return playedChunks;
      } catch (error) {
        if (sessionId !== this._speechPlaybackSession || abortController?.signal?.aborted || error?.name === 'AbortError') {
          return playedChunks;
        }
        error.playedChunks = playedChunks;
        throw error;
      } finally {
        if (this._speechPlaybackAbortController === abortController) {
          this._speechPlaybackAbortController = null;
        }
      }
    },

    async _speakBrowserChunks(chunks, sessionId) {
      if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === 'undefined') return false;
      this._speechSynthActive = true;
      try {
        for (const chunk of chunks) {
          if (sessionId !== this._speechPlaybackSession) return false;
          await new Promise((resolve, reject) => {
            let settled = false;
            const finish = (error = null) => {
              if (settled) return;
              settled = true;
              if (this._speechPlaybackResolveCurrent === finish) {
                this._speechPlaybackResolveCurrent = null;
              }
              if (sessionId !== this._speechPlaybackSession) {
                resolve();
                return;
              }
              if (error) reject(error);
              else resolve();
            };
            const utterance = new SpeechSynthesisUtterance(chunk);
            const bestVoice = this._pickBestBrowserVoice();
            if (bestVoice) {
              utterance.voice = bestVoice;
              utterance.lang = bestVoice.lang || 'en-GB';
            } else {
              utterance.lang = 'en-GB';
            }
            utterance.rate = this.voiceSpeechRate();
            utterance.pitch = this.voiceSpeechPitch();
            utterance.volume = 1.0;
            utterance.onend = () => finish();
            utterance.onerror = (event) => finish(new Error(event?.error || 'Speech synthesis failed'));
            this._speechPlaybackResolveCurrent = finish;
            window.speechSynthesis.speak(utterance);
          });
        }
        return true;
      } finally {
        if (sessionId === this._speechPlaybackSession) {
          this._speechSynthActive = false;
        }
      }
    },

    cloudSpeechSynthesisAvailable() {
      return !!(
        this.voiceStatus?.cloud_synthesis_available
        || (typeof this.azureSpeechConfigured === 'function' && this.azureSpeechConfigured())
      );
    },

    async speakMessage(text, options = {}) {
      const chunks = this._speechChunks(text);
      if (!chunks.length) return;
      const kind = String(options?.kind || 'reply').trim().toLowerCase() === 'status' ? 'status' : 'reply';
      const speakingReply = this._speechPlaybackKind === 'reply' && this.voiceSpeechBusy();
      if (kind === 'status' && speakingReply) {
        return false;
      }
      if (kind === 'status' && this.voiceSpeechBusy()) {
        return false;
      }
      this.stopSpeech();
      const spokenText = chunks.join(' ');
      const sessionId = Number(this._speechPlaybackSession || 0) + 1;
      this._speechPlaybackSession = sessionId;
      this._speechPlaybackPending = true;
      this._speechPlaybackKind = kind;
      if (kind === 'reply') {
        this.onVoiceReplyPlaybackStarted?.(spokenText);
      }

      try {
        if (this.cloudSpeechSynthesisAvailable?.()) {
          try {
            await this._playAzureSpeechChunks(chunks, sessionId);
            if (sessionId === this._speechPlaybackSession) {
              if (kind === 'reply') {
                this.onVoiceReplyPlaybackComplete?.(spokenText);
              }
              this._speechPlaybackKind = '';
            }
            return;
          } catch (error) {
            if (sessionId !== this._speechPlaybackSession) return;
            if (Number(error?.playedChunks || 0) > 0) {
              this.showToast?.('Voice playback stopped before the full reply finished');
              return;
            }
          }
        }

        const spoke = await this._speakBrowserChunks(chunks, sessionId);
        if (spoke && sessionId === this._speechPlaybackSession) {
          if (kind === 'reply') {
            this.onVoiceReplyPlaybackComplete?.(spokenText);
          }
          this._speechPlaybackKind = '';
        }
        if (!spoke && sessionId === this._speechPlaybackSession) {
          this.showToast?.('Speech playback is not available in this browser');
        }
      } finally {
        if (sessionId === this._speechPlaybackSession) {
          this._speechPlaybackPending = false;
          if (!this._currentAudio && !this._speechSynthActive) {
            this._speechPlaybackKind = '';
          }
        }
      }
      return true;
    },

    toggleVoiceMode() {
      this.voiceMode = !this.voiceMode;
      this.showToast(this.voiceMode ? 'Voice mode ON — responses will be spoken' : 'Voice mode OFF');
    },

    orbState() {
      if (this.voiceActive) return 'listening';
      if (this.voiceSpeechBusy()) return 'speaking';
      if (this.chatLoading) return 'thinking';
      if (this.agentMode) return 'agent';
      return 'idle';
    },

    autoSpeakResponse(text) {
      // Cancel any in-flight narration so it doesn't talk over the final reply
      if (typeof this._cancelNarrationQueue === 'function') {
        this._cancelNarrationQueue();
      }
      this.onVoiceResponseReady?.(text);
      if (this.voiceMode && this.speechOutputSupported) {
        this.speakMessage(text);
      }
    },

  };
}

window.axonVoicePlaybackMixin = axonVoicePlaybackMixin;
