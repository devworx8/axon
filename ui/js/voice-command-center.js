/* ══════════════════════════════════════════════════════════════
   Axon — Voice Command Center Module
   ══════════════════════════════════════════════════════════════ */

function axonVoiceCommandCenterMixin() {
  return {

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
      return typeof this.orbState === 'function' ? this.orbState() : 'idle';
    },

    voiceVisualPalette() {
      const state = this.voiceVisualState();
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
