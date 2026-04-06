/* ══════════════════════════════════════════════════════════════
   Axon — Voice Command Center Module
   ══════════════════════════════════════════════════════════════ */

function axonVoiceCommandCenterMixin() {
  return {

    /** Sleep state — when true the reactor goes dark */
    reactorAsleep: false,

    /** Tap the ORB: asleep → wake, awake → sleep */
    toggleReactorOrbAction() {
      if (this.reactorAsleep) {
        this.wakeReactor();
        return;
      }
      // Any awake state — tap puts reactor to sleep
      this.sleepReactor();
    },

    /** Put reactor to sleep — play power-down sound, speak goodbye, then dim */
    sleepReactor() {
      clearTimeout(this._bootGreetingTimer);
      if (typeof this.stopSpeech === 'function') this.stopSpeech();
      if (window.axonVoiceSleepSound) {
        window.axonVoiceSleepSound.play();
      }
      this._speakGreeting(this._pickSleepGoodbye());
      this.reactorAsleep = true;
    },

    /** Wake reactor — re-ignite glow + boot sound */
    wakeReactor() {
      this.reactorAsleep = false;
      // Re-trigger ignite animations by removing and re-adding the class
      document.querySelectorAll('.axon-reactor').forEach(svg => {
        svg.classList.add('reactor--reignite');
        requestAnimationFrame(() => {
          svg.classList.remove('reactor--reignite');
        });
      });
      if (window.axonVoiceBootSound) {
        window.axonVoiceBootSound.play();
      }
      // JARVIS-style greeting after boot sound finishes (~6.5s)
      this._scheduleBootGreeting();
    },

    /** Speak a contextual greeting once the boot animation settles */
    _scheduleBootGreeting() {
      clearTimeout(this._bootGreetingTimer);
      this._bootGreetingTimer = setTimeout(() => {
        if (!this.showVoiceOrb || this.reactorAsleep) return;
        const greeting = this._pickBootGreeting();
        this._speakGreeting(greeting);
      }, 6800);
    },

    /** Speak greeting at a slow, deliberate JARVIS pace using the configured voice */
    _speakGreeting(text) {
      // Force a slow greeting rate that bypasses the normal clamp
      this._greetingRateOverride = 0.15;
      if (typeof this.speakMessage === 'function') {
        this.speakMessage(text).finally(() => {
          this._greetingRateOverride = null;
        });
      }
    },

    /** Pick a time-aware JARVIS-style greeting */
    _pickBootGreeting() {
      const hour = new Date().getHours();
      const timeWord = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';

      const greetings = [
        `Good ${timeWord}, Sir. All systems are online.`,
        `Reactor online. Standing by, Sir.`,
        `Good ${timeWord}, Sir. Axon is ready for your command.`,
        `Systems nominal. How can I help you, Sir?`,
        `Online and operational. Good ${timeWord}, Sir.`,
      ];
      return greetings[Math.floor(Math.random() * greetings.length)];
    },

    /** Pick a JARVIS-style goodbye when going to sleep */
    _pickSleepGoodbye() {
      const goodbyes = [
        'Going offline, Sir. I\'ll be here when you need me.',
        'Reactor powering down. Rest well, Sir.',
        'Standing down, Sir. Systems on standby.',
      ];
      return goodbyes[Math.floor(Math.random() * goodbyes.length)];
    },

    async startVoiceListening() {
      if (this.voiceActive) {
        await this.startVoice();
        if (String(this.voiceTranscript || '').trim()) {
          await this.sendVoiceCommand();
        }
        return;
      }
      this._voiceResponseDismissedAt = 0;
      this.openVoiceCommandCenter?.();
      await this.startVoice();
    },

    voiceRecordingActive() {
      return !!this.voiceActive;
    },

    voiceLatestResponseMarker() {
      const message = typeof this.latestAssistantMessage === 'function'
        ? this.latestAssistantMessage()
        : [...(Array.isArray(this.chatMessages) ? this.chatMessages : [])].reverse().find(item => item?.role === 'assistant');
      return Number(message?.id)
        || Date.parse(String(message?.created_at || ''))
        || 0;
    },

    voiceLatestResponseText(limit = 6000) {
      const message = typeof this.latestAssistantMessage === 'function'
        ? this.latestAssistantMessage()
        : [...(Array.isArray(this.chatMessages) ? this.chatMessages : [])].reverse().find(item => item?.role === 'assistant');
      const content = String(message?.content || '').trim();
      if (!content) {
        if (this.chatLoading) return String(this.liveOperator?.detail || '').trim();
        return '';
      }
      const messageMarker = this.voiceLatestResponseMarker();
      if (messageMarker && Number(this._voiceResponseDismissedAt || 0) >= messageMarker) {
        return '';
      }
      return content.slice(0, limit);
    },

    voiceResponseAvailable() {
      return !!this.voiceLatestResponseText();
    },

    voiceDisplayTranscript() {
      return String(this.voiceTranscript || '').trim() || 'Waiting for a voice command…';
    },

    voiceDisplayResponse() {
      const text = this.voiceLatestResponseText();
      if (text) return text;
      if (this.chatLoading) return 'Axon is processing your request…';
      return 'The latest voice response will appear here.';
    },

    voiceCanClear() {
      return !!(String(this.voiceTranscript || '').trim() || this.voiceResponseAvailable());
    },

    clearVoiceCommandCenterState() {
      this.clearVoiceTranscript?.();
      this._voiceResponseDismissedAt = this.voiceLatestResponseMarker();
    },

    voiceStatusLabel() {
      return typeof this.voiceCenterStatusLabel === 'function'
        ? this.voiceCenterStatusLabel()
        : 'Voice command center';
    },

    voiceStateCaption() {
      const state = typeof this.orbState === 'function' ? this.orbState() : 'idle';
      if (this.reactorAsleep) return 'Sleeping — tap to wake';
      if (state === 'listening') return 'Microphone live';
      if (state === 'speaking') return 'Reply playback';
      if (state === 'thinking') return 'Reasoning in progress';
      if (state === 'agent') return 'Agent systems ready';
      return 'Standby';
    },

    voiceStatusHint() {
      return typeof this.voiceCenterStatusDetail === 'function'
        ? this.voiceCenterStatusDetail()
        : '';
    },

    voiceVisualState() {
      if (this.reactorAsleep) return 'sleep';
      return typeof this.orbState === 'function' ? this.orbState() : 'idle';
    },

    voiceVisualPalette() {
      const state = this.voiceVisualState();
      if (state === 'sleep') {
        return {
          stroke: 'rgba(51, 65, 85, 0.3)',
          glow: 'rgba(0, 0, 0, 0)',
          beamOpacity: 0.08,
          ringOpacity: 0.12,
          strokeWidth: 1.2,
        };
      }
      if (state === 'listening') {
        return {
          stroke: 'rgba(103, 232, 249, 0.92)',
          glow: 'rgba(34, 211, 238, 0.34)',
          beamOpacity: 0.92,
          ringOpacity: 0.78,
          strokeWidth: 2.7,
        };
      }
      if (state === 'speaking') {
        return {
          stroke: 'rgba(191, 219, 254, 0.86)',
          glow: 'rgba(96, 165, 250, 0.3)',
          beamOpacity: 0.82,
          ringOpacity: 0.68,
          strokeWidth: 2.45,
        };
      }
      if (state === 'thinking') {
        return {
          stroke: 'rgba(96, 165, 250, 0.72)',
          glow: 'rgba(59, 130, 246, 0.26)',
          beamOpacity: 0.62,
          ringOpacity: 0.54,
          strokeWidth: 2.2,
        };
      }
      if (state === 'agent') {
        return {
          stroke: 'rgba(251, 191, 36, 0.72)',
          glow: 'rgba(245, 158, 11, 0.22)',
          beamOpacity: 0.58,
          ringOpacity: 0.5,
          strokeWidth: 2,
        };
      }
      return {
        stroke: 'rgba(100, 116, 139, 0.52)',
        glow: 'rgba(71, 85, 105, 0.14)',
        beamOpacity: 0.28,
        ringOpacity: 0.34,
        strokeWidth: 1.8,
      };
    },

    voiceRingStyle(index = 0) {
      const palette = this.voiceVisualPalette();
      const opacity = Math.max(0.16, palette.ringOpacity - (index * 0.16));
      const width = Math.max(1.2, palette.strokeWidth - (index * 0.28));
      return `fill:none;stroke:${palette.stroke};stroke-width:${width};opacity:${opacity};`;
    },

    voiceBeamStyle(multiplier = 1) {
      const palette = this.voiceVisualPalette();
      const opacity = Math.max(0.18, palette.beamOpacity * Number(multiplier || 1));
      return `opacity:${opacity};`;
    },

    voiceGlowStyle() {
      const palette = this.voiceVisualPalette();
      return `fill:${palette.glow};opacity:1;`;
    },

  };
}

window.axonVoiceCommandCenterMixin = axonVoiceCommandCenterMixin;
