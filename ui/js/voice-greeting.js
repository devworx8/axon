/* ══════════════════════════════════════════════════════════════
   Axon — Voice Greeting Module
   Extracted from voice-command-center.js to keep bounded context.
   Handles boot greeting, reconnect greeting, sleep goodbye,
   and the visual greeting toast.
   ══════════════════════════════════════════════════════════════ */

function axonVoiceGreetingMixin() {
  const trimText = (value = '') => String(value || '').trim();

  return {
    _bootGreetingTimer: null,
    _hasGreeted: false,

    /** Schedule the initial JARVIS-style greeting after boot (once per page load) */
    _scheduleBootGreeting() {
      if (this._hasGreeted) return;
      clearTimeout(this._bootGreetingTimer);
      const delay = (this.currentWorkspaceRunActive?.() || this.chatLoading || this.liveOperator?.active) ? 520 : 6800;
      this._bootGreetingTimer = setTimeout(() => {
        if (this._hasGreeted) return;
        if (!this.showVoiceOrb || this.reactorAsleep) return;
        this._hasGreeted = true;
        const greeting = this._pickBootGreeting();
        this._speakGreeting(greeting);
        this._showGreetingToast(greeting);
      }, delay);
    },

    /**
     * Show a visual greeting toast that materialises briefly,
     * so even if voice is muted the user sees the greeting.
     */
    _showGreetingToast(text) {
      const existing = document.getElementById('voice-greeting-toast');
      if (existing) existing.remove();
      const toast = document.createElement('div');
      toast.id = 'voice-greeting-toast';
      toast.className = 'voice-greeting-toast';
      toast.textContent = text;
      const mount = document.querySelector('.voice-command-center') || document.body;
      mount.appendChild(toast);
      setTimeout(() => { toast.classList.add('voice-greeting-toast--exit'); }, 4200);
      setTimeout(() => { toast.remove(); }, 4800);
    },

    /**
     * Called when Axon server reconnects after a drop.
     * Always greets — no debounce against previous greeting.
     */
    onAxonReconnected() {
      if (!this.showVoiceOrb || this.reactorAsleep) return;
      clearTimeout(this._bootGreetingTimer);
      const greeting = 'Back online, Sir. Connection restored.';
      this._speakGreeting(greeting);
      this._showGreetingToast(greeting);
    },

    /** Speak greeting using the configured voice profile */
    _speakGreeting(text) {
      if (typeof this.speakMessage === 'function') {
        this.speakMessage(text, { kind: 'status' });
      }
    },

    /** Pick a time-aware JARVIS-style greeting */
    _pickBootGreeting() {
      if (this.currentWorkspaceRunActive?.() || this.chatLoading || this.liveOperator?.active) {
        const headline = trimText(this.voiceOperatorHeadline?.() || this.liveOperator?.title || 'the active task');
        const nextStep = trimText(this.voiceOperatorNextStep?.() || this.liveOperator?.detail || '');
        const busyLine = nextStep && nextStep !== headline
          ? `Resuming the active task, Sir. ${headline}. ${nextStep}`
          : `Resuming the active task, Sir. ${headline}`;
        return busyLine.slice(0, 220);
      }
      if (this.voiceConversation?.awaitingReply) {
        return "I'm still with you, Sir. Awaiting your next instruction.";
      }

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
  };
}

window.axonVoiceGreetingMixin = axonVoiceGreetingMixin;
