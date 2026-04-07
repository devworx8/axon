/* ══════════════════════════════════════════════════════════════
   Axon — Voice HUD (Heads-Up Display) Module
   JARVIS-style holographic overlays for the voice command center
   ══════════════════════════════════════════════════════════════ */

function axonVoiceHudMixin() {
  const trimText = (value = '') => String(value || '').trim();

  const prettyToolName = (value = '') => {
    const raw = trimText(value).replace(/[_-]+/g, ' ');
    return raw ? raw.replace(/\b\w/g, (char) => char.toUpperCase()) : 'Tool';
  };

  const clip = (value = '', limit = 180) => {
    const text = trimText(value);
    if (!text) return '';
    return text.length > limit ? `${text.slice(0, Math.max(0, limit - 1))}…` : text;
  };

  const primaryArgLine = (args = {}) => {
    const pairs = [
      ['q', args.q],
      ['path', args.path],
      ['url', args.url],
      ['location', args.location],
      ['ticker', args.ticker],
      ['id', args.idOrUrl],
      ['file', args.file],
      ['branch', args.branch_name],
    ];
    const match = pairs.find(([, value]) => trimText(value));
    if (!match) return '';
    return `· ${match[0]}: ${clip(match[1], 120)}`;
  };

  const buildOperatorTrace = (event = {}) => {
    const type = trimText(event.type || event.action).toLowerCase();
    const toolName = trimText(event.name || event.tool);
    const args = event.args && typeof event.args === 'object' ? event.args : {};
    const result = clip(event.result || event.message || event.chunk || event.detail, 180);
    const command = trimText(args.cmd || args.command || args.script);
    const cwd = trimText(args.cwd || args.workdir);
    const title = toolName ? `${prettyToolName(toolName)} telemetry` : 'Live operator telemetry';
    if (!type) return null;

    if (type === 'tool_call') {
      const lines = [];
      if (command) lines.push(`$ ${clip(command, 180)}`);
      else lines.push(`> ${prettyToolName(toolName)}`);
      if (cwd) lines.push(`@ ${clip(cwd, 140)}`);
      const argLine = primaryArgLine(args);
      if (argLine) lines.push(argLine);
      else if (!command && Object.keys(args).length) lines.push(`· ${clip(JSON.stringify(args), 150)}`);
      return { title, lines };
    }
    if (type === 'tool_result') {
      const tone = /^(ERROR:|BLOCKED_|!)/.test(result) ? '!' : '#';
      return {
        title,
        lines: [result ? `${tone} ${result}` : '# Tool completed'],
      };
    }
    if (type === 'thinking') {
      return {
        title: 'Planning telemetry',
        lines: [`# ${result || 'Axon is reasoning through the next step.'}`],
      };
    }
    if (type === 'text') {
      return {
        title: 'Response telemetry',
        lines: [`# ${result || 'Axon is drafting the reply.'}`],
      };
    }
    if (type === 'approval_required') {
      return {
        title: 'Approval telemetry',
        lines: [`? ${result || 'Approval is required before Axon can continue.'}`],
      };
    }
    if (type === 'error') {
      return {
        title: 'Recovery telemetry',
        lines: [`! ${result || 'Axon hit an error and stopped safely.'}`],
      };
    }
    if (type === 'done') {
      return {
        title: 'Completion telemetry',
        lines: ['# Task complete'],
      };
    }
    return null;
  };

  return {

    // ── HUD state ──
    hudTerminalVisible: false,
    hudTerminalLines: [],
    hudTerminalTitle: '',
    hudOperatorTraceLines: [],
    hudOperatorTraceTitle: '',
    hudOperatorTraceUpdatedAt: '',
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

    hudResetOperatorTrace(title = '') {
      this.hudOperatorTraceLines = [];
      this.hudOperatorTraceTitle = trimText(title);
      this.hudOperatorTraceUpdatedAt = '';
    },

    hudOperatorTraceLinesSnapshot(limit = 12) {
      return Array.isArray(this.hudOperatorTraceLines)
        ? this.hudOperatorTraceLines.slice(-Math.max(1, limit))
        : [];
    },

    hudRecordOperatorTrace(event = {}) {
      const trace = buildOperatorTrace(event);
      if (!trace) return;
      if (trimText(trace.title)) this.hudOperatorTraceTitle = trimText(trace.title);
      const nextLines = Array.isArray(trace.lines) ? trace.lines : [];
      nextLines.forEach((line) => {
        const text = clip(line, 220);
        if (!text) return;
        const last = this.hudOperatorTraceLines[this.hudOperatorTraceLines.length - 1];
        if (last === text) return;
        this.hudOperatorTraceLines = [...this.hudOperatorTraceLines.slice(-17), text];
      });
      this.hudOperatorTraceUpdatedAt = new Date().toISOString();
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
      const detail = String(event.message || event.detail || event.tool || '');
      const hint = `${type} ${String(event.name || '')} ${detail}`.toLowerCase();

      this.hudRecordOperatorTrace(event);

      // Terminal commands
      if (hint.includes('shell') || hint.includes('terminal') || hint.includes('command') || hint.includes('exec')) {
        this.hudActivateTool('terminal');
      }
      // File operations
      if (hint.includes('file') || hint.includes('read') || hint.includes('write') || hint.includes('edit')) {
        this.hudActivateTool('file');
      }
      // Browser
      if (hint.includes('browser') || hint.includes('fetch') || hint.includes('screenshot')) {
        this.hudActivateTool('browser');
      }
      // Search
      if (hint.includes('search') || hint.includes('grep') || hint.includes('find')) {
        this.hudActivateTool('search');
      }
      // Scan
      if (hint.includes('scan')) {
        this.hudStartScan(detail || 'Scanning workspace...');
      }
      // API call
      if (hint.includes('api') || hint.includes('provider') || hint.includes('model')) {
        const provider = detail || 'API';
        this.hudShowBeam(provider);
        this.hudActivateTool('api');
        setTimeout(() => this.hudHideBeam(), 2500);
      }
      // Approval
      if (hint.includes('approval') || hint.includes('confirm') || hint.includes('approve')) {
        this.hudShowApproval(detail);
      }
    },

  };
}

window.axonVoiceHudMixin = axonVoiceHudMixin;
