/* ══════════════════════════════════════════════════════════════
   Axon — Terminal Xterm Runtime
   Interactive PTY surfaces for console and voice command center.
   ══════════════════════════════════════════════════════════════ */

function axonTerminalXtermMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const clipText = (value = '', max = 120) => {
    const text = trimText(value);
    return text.length > max ? `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…` : text;
  };

  const xtermCtor = () => (window.Terminal || (typeof Terminal !== 'undefined' ? Terminal : null));
  const fitAddonCtor = () => {
    if (window.FitAddon?.FitAddon) return window.FitAddon.FitAddon;
    if (typeof FitAddon !== 'undefined' && FitAddon?.FitAddon) return FitAddon.FitAddon;
    return null;
  };
  const webLinksAddonCtor = () => {
    if (window.WebLinksAddon?.WebLinksAddon) return window.WebLinksAddon.WebLinksAddon;
    if (typeof WebLinksAddon !== 'undefined' && WebLinksAddon?.WebLinksAddon) return WebLinksAddon.WebLinksAddon;
    return null;
  };

  const decodeTerminalChunk = (payload = '') => {
    try {
      const raw = atob(String(payload || ''));
      const bytes = Uint8Array.from(raw, (char) => char.charCodeAt(0));
      return new TextDecoder().decode(bytes);
    } catch (_) {
      return '';
    }
  };

  const resetViewportState = (state, sessionId = '') => {
    state.sessionId = String(sessionId || '');
    state.connected = false;
    state.connecting = false;
    state.ready = false;
    state.error = '';
    state.lastCloseCode = 0;
    state.lastCloseReason = '';
    state.lastExitCode = null;
    state.lastStartedAt = '';
  };

  return {
    terminalViewportRegistry: {},

    terminalXtermSupported() {
      return !!(xtermCtor() && fitAddonCtor());
    },

    terminalViewportStateFor(view = 'console') {
      if (!this.terminalViewportRegistry || typeof this.terminalViewportRegistry !== 'object') {
        this.terminalViewportRegistry = {};
      }
      if (!this.terminalViewportRegistry[view]) {
        this.terminalViewportRegistry[view] = {
          sessionId: '',
          connected: false,
          connecting: false,
          ready: false,
          error: '',
          lastCloseCode: 0,
          lastCloseReason: '',
          lastExitCode: null,
          lastStartedAt: '',
        };
      }
      return this.terminalViewportRegistry[view];
    },

    terminalViewportControllerFor(view = 'console') {
      if (!this._terminalViewportControllers || typeof this._terminalViewportControllers !== 'object') {
        this._terminalViewportControllers = {};
      }
      if (!this._terminalViewportControllers[view]) {
        this._terminalViewportControllers[view] = {
          view,
          mount: null,
          term: null,
          fit: null,
          socket: null,
          observer: null,
          sessionId: '',
        };
      }
      return this._terminalViewportControllers[view];
    },

    terminalViewportMountRef(view = 'console') {
      return view === 'voice' ? 'voiceXtermMount' : 'consoleXtermMount';
    },

    terminalViewportMountNode(view = 'console') {
      return this.$refs?.[this.terminalViewportMountRef(view)] || null;
    },

    terminalViewportShouldMount(view = 'console') {
      if (view === 'voice') {
        return !!(
          this.showVoiceOrb
          && this.hudTerminalVisible
          && (
            this.voiceConversation?.terminalPinned
            || this.voiceTerminalAutoDockActive?.()
          )
        );
      }
      return !!(this.activeTab === 'chat' && (this.terminal?.panelOpen || this.composerOptions?.terminal_mode));
    },

    interactiveTerminalPreferred(view = 'console') {
      return this.terminalXtermSupported() && this.terminalViewportShouldMount(view);
    },

    interactiveTerminalRenderable(view = 'console') {
      return this.interactiveTerminalPreferred(view) && !this.terminalViewportError(view);
    },

    terminalViewportReady(view = 'console') {
      return !!this.terminalViewportStateFor(view).ready;
    },

    terminalViewportConnected(view = 'console') {
      return !!this.terminalViewportStateFor(view).connected;
    },

    terminalViewportError(view = 'console') {
      return trimText(this.terminalViewportStateFor(view).error);
    },

    terminalViewportStatusLabel(view = 'console') {
      const state = this.terminalViewportStateFor(view);
      if (state.error) return 'Fallback active';
      if (state.connecting) return 'Booting PTY shell';
      if (state.connected) return 'Live PTY shell';
      if (state.lastExitCode != null) return `Shell exited (${state.lastExitCode})`;
      return 'Awaiting shell';
    },

    terminalViewportOverlayTitle(view = 'console') {
      const state = this.terminalViewportStateFor(view);
      if (!this.terminalXtermSupported()) return 'xterm unavailable';
      if (state.error) return 'Interactive shell unavailable';
      if (state.connecting) return 'Spooling the shell';
      if (state.lastExitCode != null) return 'Shell session paused';
      return view === 'voice' ? 'Terminal dock on standby' : 'Interactive shell on standby';
    },

    terminalViewportOverlayDetail(view = 'console') {
      const state = this.terminalViewportStateFor(view);
      if (!this.terminalXtermSupported()) return 'This browser did not load the xterm runtime.';
      if (state.error) return state.error;
      if (state.connecting) return 'Axon is attaching a guarded PTY to the current workspace.';
      if (state.lastExitCode != null) return 'Press Focus or reopen the shell to continue.';
      return view === 'voice'
        ? 'The live terminal will boot here as soon as voice mode requests a shell surface.'
        : 'Open the guarded terminal to attach a full interactive shell to the current workspace.';
    },

    terminalViewportCaption(view = 'console') {
      if (view === 'voice') {
        return this.terminalViewportConnected(view)
          ? 'Interactive shell online. Telemetry still mirrors below the screen.'
          : 'Voice mode keeps the shell docked while the live terminal chip is armed.';
      }
      return this.terminalViewportConnected(view)
        ? 'Interactive PTY attached to the current workspace.'
        : 'The guarded terminal now boots a real PTY shell instead of a static event list.';
    },

    terminalViewportCloseFailureDetail(view = 'console', event = {}) {
      const code = Number(event?.code || 0);
      const reason = trimText(event?.reason || '');
      if (code === 4001 || /authentication required/i.test(reason)) {
        return 'Authentication required. Unlock Axon again to attach the interactive shell.';
      }
      if ((!this.authToken || !this.authenticated) && (code === 1006 || !code)) {
        return 'Authentication required. Unlock Axon again to attach the interactive shell.';
      }
      if (reason) return reason;
      return 'The PTY websocket handshake failed before Axon could attach the interactive shell.';
    },

    terminalViewportCwd(view = 'console') {
      const liveSession = view === 'voice' ? this.dashboardLiveTerminalSession?.() : null;
      return trimText(
        liveSession?.cwd
        || this.currentTerminalSession?.()?.cwd
        || this.terminal?.sessionDetail?.cwd
        || this.chatProject?.path
        || ''
      );
    },

    terminalViewportSession(view = 'console') {
      const liveSession = view === 'voice' ? this.dashboardLiveTerminalSession?.() : null;
      return liveSession || this.currentTerminalSession?.() || this.terminal?.sessionDetail || null;
    },

    terminalViewportSessionLabel(view = 'console') {
      const session = this.terminalViewportSession(view);
      return trimText(session?.title || (view === 'voice' ? 'Voice shell' : 'Console shell')) || 'Terminal';
    },

    terminalViewportActiveCommand(view = 'console') {
      const session = this.terminalViewportSession(view);
      const active = trimText(session?.active_command);
      if (active) return active;
      const events = Array.isArray(this.terminal?.sessionDetail?.recent_events)
        ? this.terminal.sessionDetail.recent_events
        : [];
      const latestCommand = [...events].reverse().find((event) => trimText(event?.event_type).toLowerCase() === 'command');
      return trimText(latestCommand?.content || '');
    },

    terminalViewportUpdatedAt(view = 'console') {
      const session = this.terminalViewportSession(view);
      return trimText(
        session?.last_output_at
        || session?.updated_at
        || this.terminalViewportStateFor(view).lastStartedAt
        || ''
      );
    },

    terminalViewportUpdatedLabel(view = 'console') {
      const stamp = this.terminalViewportUpdatedAt(view);
      if (!stamp) return '';
      if (typeof this.timeAgo === 'function') {
        try {
          return this.timeAgo(stamp);
        } catch (_) {}
      }
      return stamp;
    },

    terminalViewportStatusTone(view = 'console') {
      const state = this.terminalViewportStateFor(view);
      const session = this.terminalViewportSession(view);
      const status = trimText(session?.status).toLowerCase();
      if (state.error) return 'danger';
      if (state.connecting) return 'boot';
      if (state.connected || session?.running) return 'live';
      if (state.lastExitCode != null || status === 'failed' || status === 'stopped') return 'warning';
      return 'idle';
    },

    terminalViewportHeadline(view = 'console') {
      const command = trimText(this.terminalViewportActiveCommand(view));
      if (command) return `Live command: ${clipText(command, view === 'voice' ? 72 : 108)}`;
      const cwd = this.terminalViewportCwd(view);
      if (cwd) return `Scoped to ${clipText(cwd, view === 'voice' ? 72 : 104)}`;
      return view === 'voice'
        ? 'Voice mode keeps the interactive shell ready when a live run needs it.'
        : 'The guarded PTY shell is ready for live commands and streamed output.';
    },

    terminalViewportMeta(view = 'console') {
      const session = this.terminalViewportSession(view);
      const state = this.terminalViewportStateFor(view);
      const command = trimText(this.terminalViewportActiveCommand(view));
      const scope = trimText(this.terminalViewportCwd(view));
      const mode = trimText(session?.mode || this.terminal?.mode || '').replace(/_/g, ' ');
      const updated = trimText(this.terminalViewportUpdatedLabel(view));
      const items = [
        {
          label: 'Status',
          value: this.terminalViewportStatusLabel(view),
          tone: this.terminalViewportStatusTone(view),
        },
        command ? {
          label: 'Command',
          value: clipText(command, view === 'voice' ? 50 : 64),
          tone: state.connected || session?.running ? 'live' : 'idle',
          mono: true,
        } : null,
        scope ? {
          label: 'Scope',
          value: clipText(scope, view === 'voice' ? 44 : 56),
          tone: 'idle',
          mono: true,
        } : null,
        mode ? {
          label: 'Mode',
          value: clipText(mode, 20),
          tone: 'idle',
        } : null,
        updated ? {
          label: 'Updated',
          value: updated,
          tone: 'idle',
        } : null,
      ].filter(Boolean);
      return items.slice(0, view === 'voice' ? 3 : 4);
    },

    terminalPtySocketKey(view = 'console', sessionId = '') {
      const value = trimText(sessionId);
      return value ? `${value}-${view}` : `${view}-shell`;
    },

    terminalPtySocketUrl(sessionId = '', view = 'console') {
      const key = encodeURIComponent(this.terminalPtySocketKey(view, sessionId));
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const token = trimText(this.authToken || '');
      const query = token ? `?token=${encodeURIComponent(token)}` : '';
      return `${protocol}//${window.location.host}/ws/pty/${key}${query}`;
    },

    async terminalViewportSessionId(view = 'console') {
      const liveSessionId = view === 'voice'
        ? Number(this.dashboardLiveTerminalSessionId?.() || 0)
        : 0;
      if (liveSessionId) {
        if (Number(this.terminal?.activeSessionId || 0) !== liveSessionId) {
          await this.loadTerminalSessionDetail?.(liveSessionId, { silent: true });
        }
        return String(liveSessionId);
      }

      let sessionId = Number(this.terminal?.activeSessionId || this.currentTerminalSession?.()?.id || 0);
      if (!sessionId) {
        await this.loadTerminalSessions?.();
        await this.ensureTerminalSession?.();
        sessionId = Number(this.terminal?.activeSessionId || this.currentTerminalSession?.()?.id || 0);
      }
      return sessionId ? String(sessionId) : '';
    },

    terminalViewportIntro(view = 'console') {
      const scope = this.terminalViewportCwd(view) || 'home scope';
      const label = this.terminalViewportSessionLabel(view);
      return [
        '\x1b[38;5;45m[Axon]\x1b[0m Interactive terminal online',
        `\x1b[90m[scope]\x1b[0m ${scope}`,
        `\x1b[90m[session]\x1b[0m ${label}`,
      ].join('\r\n') + '\r\n';
    },

    focusInteractiveTerminalViewport(view = 'console') {
      try {
        this.terminalViewportControllerFor(view).term?.focus?.();
      } catch (_) {}
    },

    interactiveTerminalTranscript(view = 'console') {
      const term = this.terminalViewportControllerFor(view).term;
      if (!term?.buffer?.active) return '';
      try {
        const lines = [];
        const buffer = term.buffer.active;
        for (let index = 0; index < buffer.length; index += 1) {
          const line = buffer.getLine(index);
          if (!line) continue;
          const text = line.translateToString(true).trimEnd();
          if (text) lines.push(text);
        }
        return lines.join('\n').trim();
      } catch (_) {
        return '';
      }
    },

    async copyInteractiveTerminalViewport(view = 'console') {
      const transcript = this.interactiveTerminalTranscript(view);
      if (!transcript) {
        this.showToast?.('Nothing to copy yet');
        return;
      }
      try {
        await navigator.clipboard.writeText(transcript);
        this.showToast?.('Terminal output copied');
      } catch (error) {
        this.showToast?.(`Copy failed: ${error.message}`);
      }
    },

    clearInteractiveTerminalViewport(view = 'console') {
      const term = this.terminalViewportControllerFor(view).term;
      if (!term) return;
      term.clear();
      term.write(this.terminalViewportIntro(view));
      this.focusInteractiveTerminalViewport(view);
    },

    sendInteractiveTerminalResize(view = 'console') {
      const controller = this.terminalViewportControllerFor(view);
      if (!controller.fit || !controller.term || controller.socket?.readyState !== WebSocket.OPEN) return;
      try {
        controller.fit.fit();
        controller.socket.send(JSON.stringify({
          type: 'resize',
          cols: controller.term.cols,
          rows: controller.term.rows,
        }));
      } catch (_) {}
    },

    teardownInteractiveTerminalViewport(view = 'console', { clearState = true } = {}) {
      const controller = this.terminalViewportControllerFor(view);
      const state = this.terminalViewportStateFor(view);
      try { controller.observer?.disconnect?.(); } catch (_) {}
      try { controller.socket?.close?.(); } catch (_) {}
      try { controller.term?.dispose?.(); } catch (_) {}
      controller.observer = null;
      controller.socket = null;
      controller.fit = null;
      controller.term = null;
      controller.sessionId = '';
      if (controller.mount) controller.mount.innerHTML = '';
      controller.mount = null;
      if (clearState) resetViewportState(state);
      else {
        state.connected = false;
        state.connecting = false;
        state.ready = false;
      }
    },

    async attachInteractiveTerminalViewport(view = 'console', sessionId = '', mountNode = null) {
      const state = this.terminalViewportStateFor(view);
      const controller = this.terminalViewportControllerFor(view);
      const node = mountNode || this.terminalViewportMountNode(view);
      if (!node || !sessionId) return;

      this.teardownInteractiveTerminalViewport(view, { clearState: false });

      const TerminalCtor = xtermCtor();
      const FitAddonCtor = fitAddonCtor();
      const WebLinksCtor = webLinksAddonCtor();
      if (!TerminalCtor || !FitAddonCtor) {
        state.error = 'xterm assets are unavailable in this browser.';
        return;
      }

      controller.mount = node;
      controller.sessionId = String(sessionId);
      state.sessionId = String(sessionId);
      state.connecting = true;
      state.connected = false;
      state.ready = false;
      state.error = '';
      state.lastCloseCode = 0;
      state.lastCloseReason = '';
      state.lastStartedAt = new Date().toISOString();

      const term = new TerminalCtor({
        allowTransparency: true,
        convertEol: true,
        cursorBlink: true,
        cursorInactiveStyle: 'none',
        fontFamily: '"JetBrains Mono", "Fira Code", monospace',
        fontSize: view === 'voice' ? 13 : 12,
        letterSpacing: 0.25,
        lineHeight: 1.25,
        scrollback: 2400,
        theme: {
          background: 'rgba(2, 6, 23, 0)',
          foreground: '#dbeafe',
          cursor: '#67e8f9',
          cursorAccent: '#020617',
          selectionBackground: 'rgba(34, 211, 238, 0.24)',
          black: '#020617',
          red: '#fb7185',
          green: '#34d399',
          yellow: '#fbbf24',
          blue: '#60a5fa',
          magenta: '#c084fc',
          cyan: '#22d3ee',
          white: '#e2e8f0',
          brightBlack: '#64748b',
          brightRed: '#fda4af',
          brightGreen: '#6ee7b7',
          brightYellow: '#fcd34d',
          brightBlue: '#93c5fd',
          brightMagenta: '#d8b4fe',
          brightCyan: '#67e8f9',
          brightWhite: '#f8fafc',
        },
      });
      const fit = new FitAddonCtor();
      term.loadAddon(fit);
      if (WebLinksCtor) {
        try { term.loadAddon(new WebLinksCtor()); } catch (_) {}
      }
      term.open(node);
      controller.term = term;
      controller.fit = fit;

      const observer = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => this.sendInteractiveTerminalResize(view))
        : null;
      if (observer) {
        observer.observe(node);
        controller.observer = observer;
      }

      const socket = new WebSocket(this.terminalPtySocketUrl(sessionId, view));
      controller.socket = socket;

      socket.addEventListener('open', () => {
        state.connecting = false;
        state.connected = true;
        state.ready = true;
        state.error = '';
        term.write(this.terminalViewportIntro(view));
        this.sendInteractiveTerminalResize(view);
        if (view === 'voice') this.focusInteractiveTerminalViewport(view);
      });

      socket.addEventListener('message', (event) => {
        try {
          const payload = JSON.parse(String(event.data || '{}'));
          if (payload.type === 'data') {
            const text = decodeTerminalChunk(payload.data);
            if (text) term.write(text);
            return;
          }
          if (payload.type === 'exit') {
            state.lastExitCode = payload.code;
            state.connected = false;
            term.writeln(`\r\n\x1b[90m[Axon]\x1b[0m PTY closed${payload.code != null ? ` (exit ${payload.code})` : ''}`);
            return;
          }
          if (payload.type === 'error') {
            state.error = trimText(payload.message || 'Terminal connection failed.');
            term.writeln(`\r\n\x1b[31m[Axon]\x1b[0m ${state.error}`);
          }
        } catch (_) {}
      });

      socket.addEventListener('close', (event) => {
        state.connecting = false;
        state.connected = false;
        state.lastCloseCode = Number(event?.code || 0);
        state.lastCloseReason = trimText(event?.reason || '');
        if (!state.ready && !state.error) {
          state.error = this.terminalViewportCloseFailureDetail(view, event);
        }
      });

      socket.addEventListener('error', () => {
        state.connecting = false;
        state.connected = false;
        state.ready = false;
        if (!state.error) {
          state.error = 'The PTY transport failed to connect.';
        }
      });

      term.onData((data) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        try {
          socket.send(JSON.stringify({ type: 'input', data }));
        } catch (_) {}
      });

      setTimeout(() => this.sendInteractiveTerminalResize(view), 60);
    },

    async syncInteractiveTerminalViewport(view = 'console') {
      const state = this.terminalViewportStateFor(view);
      if (!this.terminalViewportShouldMount(view)) {
        this.teardownInteractiveTerminalViewport(view);
        return;
      }
      if (!this.terminalXtermSupported()) {
        state.error = 'xterm was not loaded, so Axon is falling back to telemetry.';
        return;
      }
      const mountNode = this.terminalViewportMountNode(view);
      if (!mountNode) return;

      const sessionId = await this.terminalViewportSessionId(view);
      if (!sessionId) {
        state.error = 'Axon could not allocate a terminal session for this surface.';
        return;
      }

      const controller = this.terminalViewportControllerFor(view);
      if (controller.term && controller.sessionId === sessionId && controller.mount === mountNode) {
        this.sendInteractiveTerminalResize(view);
        return;
      }
      if (state.connecting && controller.sessionId === sessionId) return;
      await this.attachInteractiveTerminalViewport(view, sessionId, mountNode);
    },
  };
}

window.axonTerminalXtermMixin = axonTerminalXtermMixin;
