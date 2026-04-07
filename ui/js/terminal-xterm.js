/* ══════════════════════════════════════════════════════════════
   Axon — Terminal Xterm Runtime
   Interactive PTY surfaces for console and voice command center.
   ══════════════════════════════════════════════════════════════ */

function axonTerminalXtermMixin() {
  const trimText = (value = '') => String(value || '').trim();

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

    terminalViewportSessionLabel(view = 'console') {
      const liveSession = view === 'voice' ? this.dashboardLiveTerminalSession?.() : null;
      const session = liveSession || this.currentTerminalSession?.() || this.terminal?.sessionDetail || null;
      return trimText(session?.title || (view === 'voice' ? 'Voice shell' : 'Console shell')) || 'Terminal';
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

      socket.addEventListener('close', () => {
        state.connecting = false;
        state.connected = false;
      });

      socket.addEventListener('error', () => {
        state.connecting = false;
        state.connected = false;
        state.ready = false;
        state.error = 'The PTY transport failed to connect.';
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
