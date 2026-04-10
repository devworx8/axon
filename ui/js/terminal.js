/* ══════════════════════════════════════════════════════════════
   Axon — Terminal Enhancement Module
   Bounded context: command history, search, named sessions,
   quick-command execution, split view state.
   ══════════════════════════════════════════════════════════════ */

function axonTerminalMixin() {
  return {

    // ── Command history (localStorage-backed) ──────────────
    _cmdHistory: JSON.parse(localStorage.getItem('axon_terminal_history') || '[]'),
    _cmdHistoryIdx: -1,
    _cmdHistoryMax: 100,

    /** Push a command to history, deduplicating the last entry. */
    pushCmdHistory(cmd) {
      const trimmed = (cmd || '').trim();
      if (!trimmed) return;
      // Don't duplicate if same as last entry
      if (this._cmdHistory.length && this._cmdHistory[0] === trimmed) return;
      this._cmdHistory.unshift(trimmed);
      if (this._cmdHistory.length > this._cmdHistoryMax) this._cmdHistory.length = this._cmdHistoryMax;
      this._cmdHistoryIdx = -1;
      try { localStorage.setItem('axon_terminal_history', JSON.stringify(this._cmdHistory)); } catch (_) {}
    },

    /** Navigate history on Up/Down arrow in the command bar. */
    handleCmdHistoryKey(event) {
      const key = event.key;
      if (key !== 'ArrowUp' && key !== 'ArrowDown') return;
      if (!this._cmdHistory.length) return;
      event.preventDefault();
      if (key === 'ArrowUp') {
        if (this._cmdHistoryIdx < this._cmdHistory.length - 1) {
          this._cmdHistoryIdx++;
        }
      } else {
        if (this._cmdHistoryIdx > 0) {
          this._cmdHistoryIdx--;
        } else {
          this._cmdHistoryIdx = -1;
          this.terminal.command = '';
          return;
        }
      }
      this.terminal.command = this._cmdHistory[this._cmdHistoryIdx] || '';
    },

    // ── Named sessions ─────────────────────────────────────

    /** Rename a terminal session (double-click on tab). */
    async renameTerminalSession(session) {
      if (!session || !session.id) return;
      const newName = prompt('Rename session:', session.title || 'Terminal');
      if (newName === null) return; // cancelled
      const trimmed = newName.trim() || 'Terminal';
      try {
        await this.api('PATCH', `/api/terminal/sessions/${session.id}`, { title: trimmed });
        session.title = trimmed;
        if (this.terminal.sessionDetail && Number(this.terminal.sessionDetail.id) === Number(session.id)) {
          this.terminal.sessionDetail.title = trimmed;
        }
        this.showToast(`Session renamed to "${trimmed}"`);
      } catch (e) {
        this.showToast(`Rename failed: ${e.message}`);
      }
    },

    // ── xterm search addon ─────────────────────────────────
    _xtermSearch: null,
    terminalSearchOpen: false,
    terminalSearchQuery: '',

    /** Load and activate xterm search addon. */
    initXtermSearch() {
      if (this._xtermSearch || !this._xtermInst) return;
      try {
        const SearchAddonClass = (typeof SearchAddon !== 'undefined' && SearchAddon.SearchAddon)
          ? SearchAddon.SearchAddon : (typeof SearchAddon !== 'undefined' ? SearchAddon : null);
        if (!SearchAddonClass) return;
        const addon = new SearchAddonClass();
        this._xtermInst.loadAddon(addon);
        this._xtermSearch = addon;
      } catch (e) {
        console.warn('xterm search addon not available:', e.message);
      }
    },

    toggleTerminalSearch() {
      this.terminalSearchOpen = !this.terminalSearchOpen;
      if (this.terminalSearchOpen) {
        if (!this._xtermSearch) this.initXtermSearch();
        this.$nextTick(() => {
          const el = document.getElementById('axon-terminal-search-input');
          if (el) el.focus();
        });
      } else {
        this.terminalSearchQuery = '';
        if (this._xtermSearch) {
          try { this._xtermSearch.clearDecorations(); } catch (_) {}
        }
      }
    },

    terminalSearchNext() {
      if (!this._xtermSearch || !this.terminalSearchQuery) return;
      this._xtermSearch.findNext(this.terminalSearchQuery, { regex: false, caseSensitive: false });
    },

    terminalSearchPrev() {
      if (!this._xtermSearch || !this.terminalSearchQuery) return;
      this._xtermSearch.findPrevious(this.terminalSearchQuery, { regex: false, caseSensitive: false });
    },

    /** Ctrl+F shortcut for terminal search. */
    handleTerminalSearchShortcut(event) {
      if ((event.ctrlKey || event.metaKey) && event.key === 'f') {
        event.preventDefault();
        event.stopPropagation();
        this.toggleTerminalSearch();
      }
    },

    // ── Split view: Console Terminal vs Safe Runner ────────
    terminalViewTab: 'console',  // 'console' | 'runner'

    // ── Quick command execution fix ────────────────────────
    /** Apply quick command and auto-execute safe presets. */
    applyAndRunQuickCommand(preset) {
      if (!preset) return;
      this.terminal.command = preset.command || '';
      if (preset.mode) this.terminal.mode = preset.mode;

      // Safe presets (no mode override = safe): execute immediately
      if (!preset.mode) {
        this.pushCmdHistory(preset.command);
        this.executeTerminalCommand(false);
      } else {
        // Presets that require approval: just load into command bar
        this.showToast(`${preset.label} loaded — click Run or Approve to execute`);
      }
    },

    // ── Wrap executeTerminalCommand to record history ──────
    async executeTerminalCommandWithHistory(approved) {
      const cmd = approved
        ? (this.terminal.pendingCommand || this.terminal.command)
        : this.terminal.command;
      if (cmd && cmd.trim()) this.pushCmdHistory(cmd);
      this._cmdHistoryIdx = -1;
      return this.executeTerminalCommand(approved);
    },

    // ── Core terminal helpers (extracted from dashboard.js) ─

    focusXterm() {
      try {
        if (this._xtermInst) this._xtermInst.focus();
      } catch (_) {}
    },

    clearInteractiveShell({ showToast = true } = {}) {
      if (!this._xtermInst) return;
      this._xtermInst.clear();
      this._xtermInst.writeln('\x1b[90mAxon Interactive Terminal — ready for the next command\x1b[0m');
      this.focusXterm();
      if (showToast) this.showToast('Interactive shell cleared');
    },

    terminalTranscript() {
      try {
        const buffer = this._xtermInst?.buffer?.active;
        if (buffer) {
          const lines = [];
          for (let i = 0; i < buffer.length; i += 1) {
            const line = buffer.getLine(i);
            if (!line) continue;
            const text = line.translateToString(true).trimEnd();
            if (text) lines.push(text);
          }
          const joined = lines.join('\n').trim();
          if (joined) return joined;
        }
      } catch (_) {}
      return (this.terminal.sessionDetail?.recent_events || [])
        .map(event => `[${event.event_type}] ${event.content || ''}`.trim())
        .filter(Boolean)
        .join('\n')
        .trim();
    },

    async copyInteractiveShell() {
      const transcript = this.terminalTranscript();
      if (!transcript) {
        this.showToast('Nothing to copy yet');
        return;
      }
      try {
        await navigator.clipboard.writeText(transcript);
        this.showToast('Terminal output copied');
      } catch (e) {
        this.showToast(`Copy failed: ${e.message}`);
      }
    },
  };
}

window.axonTerminalMixin = axonTerminalMixin;

/* ══════════════════════════════════════════════════════════════
   Axon — Terminal Command Dispatch (PTY-first)
   Bounded context: classify shell commands and enforce PTY-first execution.
   ══════════════════════════════════════════════════════════════ */

function axonTerminalCommandDispatchMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const shellPrefix = /^(git|npm|npx|pnpm|yarn|python3?|node|bash|sh|zsh|rg|ripgrep|ls|cat|sed|awk|grep|find|fd|tree|make|go|cargo|pip3?|poetry|uv|pytest|docker|kubectl)\b/i;
  const shellOperators = /[;&|]/;

  return {
    terminalCommandRequiresPty(command = '') {
      const raw = trimText(command);
      if (!raw) return false;
      if (shellOperators.test(raw)) return true;
      return shellPrefix.test(raw);
    },

    terminalCommandExecutionView() {
      return this.showVoiceOrb ? 'voice' : 'console';
    },

    async waitForTerminalViewport(view = 'console', timeoutMs = 1600) {
      const started = Date.now();
      return new Promise(resolve => {
        const tick = () => {
          if (this.terminalViewportConnected?.(view)) return resolve(true);
          if (Date.now() - started >= timeoutMs) return resolve(false);
          requestAnimationFrame(tick);
        };
        tick();
      });
    },

    async prepareInteractiveTerminal(view = 'console') {
      if (view === 'voice') {
        this.ensureVoiceConversationState?.();
        if (typeof this.voiceConversation.terminalPinnedTouched !== 'boolean') {
          this.voiceConversation.terminalPinnedTouched = false;
        }
        this.voiceConversation.terminalPinned = true;
        this.hudShowTerminal?.('Terminal');
        this.syncVoiceCommandCenterRuntime?.();
        this.focusInteractiveTerminalViewport?.('voice');
        await this.waitForTerminalViewport('voice', 1800);
        return;
      }
      this.terminal.panelOpen = true;
      this.composerOptions.terminal_mode = true;
      this.syncVoiceCommandCenterRuntime?.();
      this.focusInteractiveTerminalViewport?.('console');
      await this.waitForTerminalViewport('console', 1800);
    },

    async executeTerminalCommand(approved = false) {
      const command = String(approved ? (this.terminal.pendingCommand || this.terminal.command) : this.terminal.command || '').trim();
      if (!command || this.terminal.executing) return;
      await this.ensureTerminalSession();
      if (!this.terminal.activeSessionId) return;
      const requirePty = this.terminalCommandRequiresPty(command);
      if (requirePty) {
        await this.prepareInteractiveTerminal(this.terminalCommandExecutionView());
      }
      this.terminal.executing = true;
      try {
        const endpoint = approved
          ? `/api/terminal/sessions/${this.terminal.activeSessionId}/approve`
          : `/api/terminal/sessions/${this.terminal.activeSessionId}/execute`;
        const result = await this.api('POST', endpoint, {
          command,
          mode: this.terminal.mode,
          require_pty: requirePty,
        });
        if (result.status === 'approval_required') {
          this.terminal.pendingCommand = result.command || command;
          this.terminal.approvalRequired = true;
          this.showToast('Approval required before Axon runs this command');
        } else if (result.status === 'blocked') {
          this.terminal.pendingCommand = '';
          this.terminal.approvalRequired = false;
          this.showToast(result.message || 'That command is blocked in read-only mode');
        } else if (result.status === 'simulation') {
          this.terminal.pendingCommand = '';
          this.terminal.approvalRequired = false;
          this.terminal.command = '';
          this.showToast(result.message || 'Simulation only');
        } else if (result.status === 'interactive_required') {
          this.terminal.pendingCommand = result.command || command;
          this.terminal.approvalRequired = false;
          this.showToast(result.message || 'Open the interactive terminal to run this command');
        } else {
          this.terminal.pendingCommand = '';
          this.terminal.approvalRequired = false;
          this.terminal.command = '';
          this.showToast('Terminal command started');
        }
        await this.loadTerminalSessionDetail(this.terminal.activeSessionId, { silent: true });
        this.syncVoiceCommandCenterRuntime?.();
      } catch (e) {
        this.showToast(`Terminal run failed: ${e.message}`);
      }
      this.terminal.executing = false;
    },
  };
}

window.axonTerminalCommandDispatchMixin = axonTerminalCommandDispatchMixin;
