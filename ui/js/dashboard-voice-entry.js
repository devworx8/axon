/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Voice Entry Fallback
   Bounded context: ensure dashboard voice entry buttons
   can open full voice mode even if Alpine bindings
   are delayed.
   ══════════════════════════════════════════════════════════════ */

(function attachDashboardVoiceEntryFallback() {
  const resolveRootState = () => {
    const root = document.documentElement;
    if (root && root.__x && root.__x.$data) return root.__x.$data;
    return null;
  };

  const openVoiceFromDashboard = () => {
    const state = resolveRootState();
    if (state && typeof state.openVoiceCommandCenter === 'function') {
      state.openVoiceCommandCenter();
      return true;
    }
    return false;
  };

  const bindButtons = () => {
    const buttons = document.querySelectorAll('[data-voice-open-full]');
    buttons.forEach((button) => {
      if (button.dataset.voiceOpenFullBound === 'true') return;
      button.dataset.voiceOpenFullBound = 'true';
      button.addEventListener('click', () => {
        openVoiceFromDashboard();
      });
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindButtons, { once: true });
  } else {
    bindButtons();
  }

  window.addEventListener('axon:dashboard-ready', bindButtons);
})();
