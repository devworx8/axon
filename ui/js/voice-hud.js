/* ══════════════════════════════════════════════════════════════
   Axon — Voice HUD (Heads-Up Display) Module
   JARVIS-style holographic overlays for the voice command center
   ══════════════════════════════════════════════════════════════ */

function axonVoiceHudMixin() {
  return {

    // ── HUD state ──
    hudTerminalVisible: false,
    hudTerminalLines: [],
    hudTerminalTitle: '',
    hudScanActive: false,
    hudScanProgress: 0,
    hudScanLabel: '',
    hudActiveTools: [],
    hudConnectionBeam: null,
    hudApprovalPending: false,
    hudApprovalDetail: '',
    _hudToolTimeout: null,

    // ══════════════════════════════════════════════════════════
    // 1. Terminal Pull-up Panel
    // ══════════════════════════════════════════════════════════

    /** Show a holographic terminal with streaming output */
    hudShowTerminal(title = 'Terminal', lines = []) {
      this.hudTerminalTitle = title;
      this.hudTerminalLines = Array.isArray(lines) ? lines.slice(-30) : [];
      this.hudTerminalVisible = true;
    },

    /** Append a line to the HUD terminal (auto-scroll) */
    hudTerminalAppend(line) {
      if (!this.hudTerminalVisible) return;
      this.hudTerminalLines.push(String(line));
      if (this.hudTerminalLines.length > 50) {
        this.hudTerminalLines = this.hudTerminalLines.slice(-30);
      }
    },

    /** Close the HUD terminal with fade-out */
    hudHideTerminal() {
      this.hudTerminalVisible = false;
      setTimeout(() => {
        this.hudTerminalLines = [];
        this.hudTerminalTitle = '';
      }, 400);
    },

    // ══════════════════════════════════════════════════════════
    // 2. File Scan Hologram
    // ══════════════════════════════════════════════════════════

    /** Start a radial scan animation around the reactor */
    hudStartScan(label = 'Scanning...') {
      this.hudScanActive = true;
      this.hudScanProgress = 0;
      this.hudScanLabel = label;
    },

    /** Update scan progress (0-100) */
    hudUpdateScan(progress, label) {
      this.hudScanProgress = Math.min(100, Math.max(0, progress));
      if (label) this.hudScanLabel = label;
    },

    /** End the scan */
    hudEndScan() {
      this.hudScanProgress = 100;
      setTimeout(() => {
        this.hudScanActive = false;
        this.hudScanProgress = 0;
        this.hudScanLabel = '';
      }, 600);
    },

    // ══════════════════════════════════════════════════════════
    // 3. Tool Activation Badges
    // ══════════════════════════════════════════════════════════

    /** Flash a tool badge around the reactor perimeter */
    hudActivateTool(toolName) {
      const icons = {
        terminal: '⬛', browser: '🌐', file: '📄', search: '🔍',
        code: '💻', api: '⚡', memory: '🧠', vision: '👁',
      };
      const icon = icons[toolName] || '⚙';
      const badge = { id: Date.now(), name: toolName, icon, active: true };
      this.hudActiveTools = [...this.hudActiveTools.slice(-5), badge];
      setTimeout(() => {
        this.hudActiveTools = this.hudActiveTools.filter(t => t.id !== badge.id);
      }, 3000);
    },

    // ══════════════════════════════════════════════════════════
    // 4. Connection Beam
    // ══════════════════════════════════════════════════════════

    /** Show a laser beam from reactor to provider chip */
    hudShowBeam(providerName) {
      this.hudConnectionBeam = providerName;
    },

    hudHideBeam() {
      this.hudConnectionBeam = null;
    },

    // ══════════════════════════════════════════════════════════
    // 5. Approval Gate Overlay
    // ══════════════════════════════════════════════════════════

    /** Show amber approval overlay */
    hudShowApproval(detail = '') {
      this.hudApprovalPending = true;
      this.hudApprovalDetail = detail;
    },

    hudDismissApproval() {
      this.hudApprovalPending = false;
      this.hudApprovalDetail = '';
    },

    // ══════════════════════════════════════════════════════════
    // 6. Auto-hook: listen to agent events and trigger HUD
    // ══════════════════════════════════════════════════════════

    /** Call from liveOperator watcher to auto-trigger HUD elements */
    hudProcessAgentEvent(event) {
      if (!event || !this.showVoiceOrb) return;
      const type = String(event.type || event.action || '').toLowerCase();
      const detail = String(event.detail || event.tool || '');

      // Terminal commands
      if (type.includes('shell') || type.includes('terminal') || type.includes('command')) {
        this.hudShowTerminal(detail || 'CLI Execution');
        this.hudActivateTool('terminal');
      }
      // File operations
      if (type.includes('file') || type.includes('read') || type.includes('write') || type.includes('edit')) {
        this.hudActivateTool('file');
      }
      // Browser
      if (type.includes('browser') || type.includes('fetch') || type.includes('screenshot')) {
        this.hudActivateTool('browser');
      }
      // Search
      if (type.includes('search') || type.includes('grep') || type.includes('find')) {
        this.hudActivateTool('search');
      }
      // Scan
      if (type.includes('scan')) {
        this.hudStartScan(detail || 'Scanning workspace...');
      }
      // API call
      if (type.includes('api') || type.includes('provider') || type.includes('model')) {
        const provider = detail || 'API';
        this.hudShowBeam(provider);
        this.hudActivateTool('api');
        setTimeout(() => this.hudHideBeam(), 2500);
      }
      // Approval
      if (type.includes('approval') || type.includes('confirm') || type.includes('approve')) {
        this.hudShowApproval(detail);
      }
    },

  };
}

window.axonVoiceHudMixin = axonVoiceHudMixin;
