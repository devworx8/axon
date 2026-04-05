/* ══════════════════════════════════════════════════════════════
   Axon — Navigation Context
   ══════════════════════════════════════════════════════════════ */

function axonNavigationMixin() {
  return {
    consoleReturnTab: 'dashboard',
    consoleReturnLabel: 'Dashboard',

    rememberConsoleOrigin(sourceTab = '') {
      const nextTab = String(sourceTab || this.activeTab || 'dashboard').trim() || 'dashboard';
      if (!nextTab || nextTab === 'chat') return;
      this.consoleReturnTab = nextTab;
      this.consoleReturnLabel = typeof this.tabLabelFor === 'function'
        ? this.tabLabelFor(nextTab)
        : nextTab;
    },

    returnFromConsole() {
      const target = String(this.consoleReturnTab || 'dashboard').trim() || 'dashboard';
      this.switchTab(target === 'chat' ? 'dashboard' : target);
    },

    consoleReturnText() {
      const label = String(this.consoleReturnLabel || '').trim();
      if (!label || label === 'Dashboard') return 'Back to Control Room';
      return `Back to ${label}`;
    },

    consoleOriginKicker() {
      const label = String(this.consoleReturnLabel || '').trim();
      if (!label || label === 'Dashboard') return 'JARVIS Tactical Console';
      return `${label} Console Link`;
    },
  };
}

window.axonNavigationMixin = axonNavigationMixin;
