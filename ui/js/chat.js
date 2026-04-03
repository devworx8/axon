/* ══════════════════════════════════════════════════════════════
   Axon — Chat Module
   ══════════════════════════════════════════════════════════════ */

function axonChatMixin() {
  return {

    /* ── Composer helpers ─────────────────────────────────────── */

    chatComposerPlaceholder() {
      if (this.chatLoading) return 'Steer agent or add to queue…';
      if (this.businessMode) {
        if (this.businessView === 'quote') return 'Create a quote for Khanyisa with line items, discount, and total...';
        if (this.businessView === 'client') return 'Draft a client profile, follow-up email, or billing summary...';
        if (this.businessView === 'receipt') return 'Create a receipt with payment confirmation details...';
        return 'Create an invoice with line items, discount, due date, and client details...';
      }
      const agent = this.resolveChatMode(this.chatInput) === 'agent';
      const opts = this.normalizedComposerOptions();
      if (!agent) {
        if (opts.intelligence_mode === 'deep_research') return 'Ask Axon to research, synthesize, and explain...';
        if (opts.action_mode === 'generate') return 'Tell Axon what to create...';
        return 'Give Axon a goal, task, or command...';
      }
      return this.isMobile
        ? 'Give Axon a goal, task, or command...'
        : 'Give Axon a goal, task, or command...';
    },

    clearChatInput() {
      this.chatInput = '';
      this.resetChatComposerHeight();
    },

    handleComposerEnter(event) {
      if (!event) return;
      if (event.isComposing || event.keyCode === 229) return;
      // If slash menu is open, Enter applies the selected command
      if (this.slashMenu?.open && this.slashMenu.filtered.length) {
        event.preventDefault();
        this.applySlashCommand(this.slashMenu.filtered[this.slashMenu.selectedIdx || 0]);
        return;
      }
      if (event.shiftKey) {
        requestAnimationFrame(() => this.resetChatComposerHeight());
        return;
      }
      event.preventDefault();
      this.sendChat();
    },

    resetChatComposerHeight() {
      this.$nextTick(() => {
        const ta = this.$refs.chatComposer;
        if (!ta) return;
        const baseHeight = this.isMobile ? 44 : 52;
        ta.style.height = baseHeight + 'px';
        if (this.chatInput.trim()) {
          ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
        }
      });
    },

    /* ── Slash-command palette ──────────────────────────────────── */

    _SLASH_COMMANDS: [
      { name: '/explain',    icon: '💡', desc: 'Explain this code / concept',         template: 'Explain: ' },
      { name: '/refactor',   icon: '♻️', desc: 'Refactor for clarity & performance',   template: 'Refactor this code:\n\n```\n\n```' },
      { name: '/debug',      icon: '🐛', desc: 'Find and fix the bug',                 template: 'Debug this:\n\n```\n\n```\n\nError: ' },
      { name: '/test',       icon: '🧪', desc: 'Write unit tests',                     template: 'Write tests for:\n\n```\n\n```' },
      { name: '/docs',       icon: '📝', desc: 'Generate docstrings / comments',       template: 'Add documentation to:\n\n```\n\n```' },
      { name: '/review',     icon: '🔍', desc: 'Code review with suggestions',         template: 'Review this code:\n\n```\n\n```' },
      { name: '/split',      icon: '✂️', desc: 'Split into modular architecture',      template: 'Refactor into modular architecture:\n\n```\n\n```\n\nSplit into: ' },
      { name: '/types',      icon: '🏷️', desc: 'Add type annotations',                 template: 'Add type annotations to:\n\n```\n\n```' },
      { name: '/fix',        icon: '🔧', desc: 'Fix the error shown',                  template: 'Fix this error:\n\n```\n\n```\n\nError:\n```\n\n```' },
      { name: '/optimize',   icon: '⚡', desc: 'Optimize for speed / memory',          template: 'Optimize this code:\n\n```\n\n```' },
      { name: '/convert',    icon: '🔄', desc: 'Convert to another language/format',   template: 'Convert this to ' },
      { name: '/summarize',  icon: '📋', desc: 'Summarize the attached content',       template: 'Summarize: ' },
    ],

    onComposerInput(e) {
      const val = e.target.value;
      const slash = val.match(/^(\/\w*)$/);
      if (slash) {
        const q = slash[1].toLowerCase();
        this.slashMenu.query = q;
        this.slashMenu.filtered = this._SLASH_COMMANDS.filter(c => c.name.startsWith(q));
        this.slashMenu.selectedIdx = 0;
        this.slashMenu.open = this.slashMenu.filtered.length > 0;
      } else {
        this.slashMenu.open = false;
      }
    },

    applySlashCommand(cmd) {
      this.chatInput = cmd.template;
      this.slashMenu.open = false;
      this.$nextTick(() => {
        const ta = this.$refs.chatComposer;
        if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
        this.resetChatComposerHeight && this.resetChatComposerHeight();
      });
    },

    handleComposerTab(e) {
      // Navigate slash menu with Tab, or insert 2-space indent when in code context
      if (this.slashMenu.open) {
        this.slashMenu.selectedIdx = (this.slashMenu.selectedIdx + 1) % (this.slashMenu.filtered.length || 1);
        return;
      }
      // Insert indent when textarea has code-like content
      const ta = e.target;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const val = ta.value;
      ta.value = val.slice(0, start) + '  ' + val.slice(end);
      ta.selectionStart = ta.selectionEnd = start + 2;
      this.chatInput = ta.value;
    },

    /* ── Image paste handler ─────────────────────────────────────── */

    async handleComposerPaste(e) {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (!item.type.startsWith('image/')) continue;
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;
        await this._uploadPastedImage(file);
        break;
      }
    },

    async _uploadPastedImage(file) {
      try {
        const fd = new FormData();
        fd.append('files', file, `paste-${Date.now()}.png`);
        if (this.chatProjectId) fd.append('workspace_id', this.chatProjectId);
        const res = await fetch('/api/resources/upload', {
          method: 'POST',
          headers: this.authHeaders(),
          body: fd,
        });
        if (res.status === 401) {
          this.handleAuthRequired();
          this.showToast('Session expired — sign in again');
          return;
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          this.showToast(data.detail || 'Image upload failed');
          return;
        }
        const item = (data?.items || [])[0];
        if (item) {
          this.selectedResources = [...(this.selectedResources || []), item];
          this.showToast('Image attached ✓');
        }
      } catch (err) {
        this.showToast(`Could not upload pasted image: ${err.message || 'request failed'}`);
      }
    },

    async handleComposerDrop(e) {
      const files = Array.from(e.dataTransfer?.files || []).filter(f => f.type.startsWith('image/'));
      if (!files.length) return;
      for (const file of files) {
        await this._uploadPastedImage(file);
      }
    },

    async handleImageUpload(event) {
      const files = Array.from(event?.target?.files || []).filter(f => f.type.startsWith('image/'));
      if (!files.length) return;
      for (const file of files) {
        await this._uploadPastedImage(file);
      }
      if (event?.target) event.target.value = '';
    },

    scrollChat(force = false) {
      if (!force && this._userScrolled) return;
      if (this._scrollRaf) cancelAnimationFrame(this._scrollRaf);
      if (this._scrollTimers?.length) {
        this._scrollTimers.forEach(timer => clearTimeout(timer));
        this._scrollTimers = [];
      }
      if (force) {
        this._userScrolled = false;
        this.showScrollToBottom = false;
      }
      const applyScroll = () => {
        const el = document.getElementById('chat-messages');
        if (!el) return;
        if (!force && this._userScrolled) return;
        const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
        if (!force && distFromBottom > 200) return;
        el.scrollTop = el.scrollHeight;
        this.showScrollToBottom = false;
      };
      this._scrollRaf = requestAnimationFrame(() => {
        this._scrollRaf = null;
        applyScroll();
      });
      if (force) {
        this._scrollTimers = [80, 220, 500].map(ms => setTimeout(applyScroll, ms));
      }
    },

    jumpChatToBottom() {
      this.scrollChat(true);
    },

    onChatScroll(e) {
      const el = e?.target || document.getElementById('chat-messages');
      if (!el) return;
      // User is considered "scrolled up" if more than 200px from the bottom
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      this._userScrolled = dist > 200;
      // Show/hide the jump-to-bottom button
      this.showScrollToBottom = this._userScrolled && this.chatLoading;
    },

    /* ── Mode resolution ──────────────────────────────────────── */

    resolveChatMode(msg) {
      const preferred = this.composerPreferredMode(msg);
      if (preferred) {
        return preferred === 'agent' && !this.currentBackendSupportsAgent() ? 'chat' : preferred;
      }
      return this.currentBackendSupportsAgent() && (this.agentMode || this.shouldAutoUseAgent(msg))
        ? 'agent'
        : 'chat';
    },

    resetPrimaryConversationModes() {
      if (!this.composerOptions) this.composerOptions = {};
      this.businessMode = false;
      this.agentMode = false;
      this.composerOptions.intelligence_mode = 'ask';
      this.composerOptions.action_mode = '';
      this.composerOptions.agent_role = '';
    },

    setConversationModeAsk(options = {}) {
      this.resetPrimaryConversationModes();
      if (options.persist === true) this.persistConversationModePreference();
    },

    setConversationModeAuto(options = {}) {
      this.resetPrimaryConversationModes();
      this.agentMode = true;
      this.composerOptions.agent_role = 'auto';
      this.composerOptions.safe_mode = true;
      this.composerOptions.require_approval = false;
      this.composerOptions.external_mode = 'local_first';
      if (options.persist === true) this.persistConversationModePreference();
    },

    setConversationModeAgent(options = {}) {
      this.resetPrimaryConversationModes();
      this.agentMode = true;
      if (this.usesOllamaBackend() && this.ollamaModels.length === 0) {
        this.loadOllamaModels();
      }
      if (options.persist === true) this.persistConversationModePreference();
    },

    setConversationModeCode(options = {}) {
      this.resetPrimaryConversationModes();
      this.composerOptions.intelligence_mode = 'analyze';
      this.composerOptions.action_mode = 'generate';
      if (options.persist === true) this.persistConversationModePreference();
    },

    setConversationModeResearch(options = {}) {
      this.resetPrimaryConversationModes();
      this.composerOptions.intelligence_mode = 'deep_research';
      if (options.persist === true) this.persistConversationModePreference();
    },

    chooseConversationModeAsk() {
      this.setConversationModeAsk({ persist: true });
    },

    chooseConversationModeAuto() {
      this.setConversationModeAuto({ persist: true });
    },

    chooseConversationModeAgent() {
      this.setConversationModeAgent({ persist: true });
    },

    chooseConversationModeCode() {
      this.setConversationModeCode({ persist: true });
    },

    chooseConversationModeResearch() {
      this.setConversationModeResearch({ persist: true });
    },

    isPrimaryConversationMode(mode) {
      const opts = this.normalizedComposerOptions();
      if (mode === 'business') return !!this.businessMode;
      if (mode === 'auto') return !this.businessMode && !!this.agentMode && opts.agent_role === 'auto';
      if (mode === 'agent') return !!this.agentMode && !this.businessMode && opts.agent_role !== 'auto';
      if (mode === 'code') {
        return !this.businessMode && !this.agentMode
          && opts.intelligence_mode === 'analyze'
          && opts.action_mode === 'generate';
      }
      if (mode === 'research') {
        return !this.businessMode && !this.agentMode
          && opts.intelligence_mode === 'deep_research';
      }
      return !this.businessMode
        && !this.agentMode
        && opts.intelligence_mode === 'ask'
        && !opts.action_mode
        && !opts.agent_role;
    },

    effectiveChatMode(msg, mode = '') {
      let effectiveMode = mode || this.resolveChatMode(msg);
      if (effectiveMode !== 'agent' && this.shouldAutoUseAgent(msg) && this.currentBackendSupportsAgent()) {
        effectiveMode = 'agent';
      }
      return effectiveMode;
    },

    isAutoRoutedAgent(msg = '') {
      if (!this.currentBackendSupportsAgent()) return false;
      if (this.businessMode || this.agentMode) return false;
      const preferred = this.composerPreferredMode(msg);
      if (preferred) return false;
      return this.shouldAutoUseAgent(msg);
    },

    composerExecutionMode(msg = '') {
      const effective = this.effectiveChatMode(msg);
      if (effective === 'agent' && this.isAutoRoutedAgent(msg)) return 'agent-auto';
      return effective;
    },

    composerExecutionLabel(msg = '') {
      const executionMode = this.composerExecutionMode(msg);
      if (executionMode === 'agent-auto') return 'Auto-routed to local operator';
      if (executionMode === 'agent' && this.autonomousConsoleActive()) return 'Autonomous operator active';
      if (executionMode === 'agent') return 'Local operator active';
      if (!this.usesOllamaBackend()) return 'External runtime active';
      return 'Chat response mode';
    },

    toggleAgentMode(force = null) {
      const enabled = typeof force === 'boolean' ? force : !this.agentMode;
      if (enabled) this.chooseConversationModeAgent();
      else this.chooseConversationModeAsk();
    },

    setAgentStage(phase) {
      if (this.agentLifecycle.includes(phase)) this.agentProgressState = phase;
    },

    activePrimaryConversationMode() {
      if (this.businessMode) return 'business';
      const opts = this.normalizedComposerOptions();
      if (this.agentMode && opts.agent_role === 'auto') return 'auto';
      if (this.agentMode) return 'agent';
      if (opts.intelligence_mode === 'analyze' && opts.action_mode === 'generate') return 'code';
      if (opts.intelligence_mode === 'deep_research') return 'research';
      return 'ask';
    },

    autonomousConsoleActive() {
      const opts = this.normalizedComposerOptions();
      return !!this.agentMode && !this.businessMode && opts.agent_role === 'auto';
    },

    persistConversationModePreference() {
      try {
        const mode = this.activePrimaryConversationMode();
        // Auto mode is session-derived, not a sticky saved default.
        // It should return on reload only when the user explicitly chose Auto
        // and there is a real resumable Auto session to re-attach to.
        if (mode === 'auto') {
          if (typeof this.writeWindowPref === 'function') this.writeWindowPref('consoleAutoIntent', 'true');
          else localStorage.setItem('axon.consoleAutoIntent', 'true');
          if (typeof this.writeWindowPref === 'function') this.writeWindowPref('consoleMode', '');
          else localStorage.removeItem('axon.consoleMode');
          return;
        }
        if (typeof this.writeWindowPref === 'function') this.writeWindowPref('consoleAutoIntent', '');
        else localStorage.removeItem('axon.consoleAutoIntent');
        if (typeof this.writeWindowPref === 'function') this.writeWindowPref('consoleMode', mode);
        else localStorage.setItem('axon.consoleMode', mode);
      } catch (_) {}
    },

    restoreConversationModePreference() {
      let saved = '';
      try {
        saved = String(
          typeof this.readWindowPref === 'function'
            ? this.readWindowPref('consoleMode', localStorage.getItem('axon.consoleMode') || '')
            : (localStorage.getItem('axon.consoleMode') || '')
        ).trim().toLowerCase();
      } catch (_) {}
      if (!saved) return;
      if (saved === 'business') {
        this.toggleBusinessMode(true);
        return;
      }
      if (saved === 'agent') {
        if (this.currentBackendSupportsAgent()) this.setConversationModeAgent();
        else this.setConversationModeAsk();
        return;
      }
      if (saved === 'auto') {
        // Legacy fallback: do not revive stale saved Auto mode here.
        // Active Auto sessions are restored later by loadAutoSessions().
        this.setConversationModeAsk();
        return;
      }
      if (saved === 'code') {
        this.setConversationModeCode();
        return;
      }
      if (saved === 'research') {
        this.setConversationModeResearch();
        return;
      }
      this.setConversationModeAsk();
    },

    setConsoleZoom(value) {
      const numeric = Number(value || 1);
      const next = Math.max(0.9, Math.min(1.45, Math.round(numeric * 100) / 100));
      this.consoleZoom = next;
      try {
        if (typeof this.writeWindowPref === 'function') this.writeWindowPref('consoleZoom', String(next));
        else localStorage.setItem('axon.consoleZoom', String(next));
      } catch (_) {}
    },

    adjustConsoleZoom(delta = 0) {
      this.setConsoleZoom((Number(this.consoleZoom || 1) || 1) + Number(delta || 0));
    },

    resetConsoleZoom() {
      this.setConsoleZoom(1);
    },

    consoleZoomPercent() {
      return `${Math.round((Number(this.consoleZoom || 1) || 1) * 100)}%`;
    },

    consoleZoomStyle() {
      const zoom = Math.max(0.9, Math.min(1.45, Number(this.consoleZoom || 1) || 1));
      return `zoom:${zoom};`;
    },

    currentThreadMode(mode = '') {
      const explicitMode = String(mode || '').trim().toLowerCase();
      if (explicitMode === 'agent') return this.autonomousConsoleActive() ? 'auto' : 'agent';
      if (explicitMode === 'chat') return this.activePrimaryConversationMode();
      return this.activePrimaryConversationMode();
    },

    conversationModeIcon(mode = 'ask') {
      const key = String(mode || 'ask').trim().toLowerCase();
      const map = {
        ask: '◌',
        auto: '✦',
        agent: '⬢',
        code: '</>',
        research: '⌕',
        business: '¤',
        recover: '!',
      };
      return map[key] || map.ask;
    },

    threadModeKey(message = {}) {
      const explicit = String(message.threadMode || '').trim().toLowerCase();
      if (explicit) return explicit;
      if (message.pendingApproval || message.interruptedSessionNotice || message.error) return 'recover';
      if (message.mode === 'agent') return 'agent';
      if (message.mode === 'chat') return 'ask';
      return 'ask';
    },

    threadModeShellClass(message = {}) {
      return `thread-mode-shell thread-mode-${this.threadModeKey(message)}`;
    },

    threadModeBubbleClass(message = {}) {
      const key = this.threadModeKey(message);
      const assistantMap = {
        ask: 'ring-1 ring-blue-400/12 shadow-blue-500/10',
        auto: 'ring-1 ring-emerald-400/18 shadow-emerald-500/10',
        agent: 'ring-1 ring-amber-400/18 shadow-amber-500/10',
        code: 'ring-1 ring-violet-400/18 shadow-violet-500/10',
        research: 'ring-1 ring-cyan-400/18 shadow-cyan-500/10',
        business: 'ring-1 ring-emerald-300/18 shadow-emerald-400/10',
        recover: 'ring-1 ring-rose-400/22 shadow-rose-500/10',
      };
      const userMap = {
        ask: 'ring-1 ring-blue-300/16 shadow-blue-500/10',
        auto: 'ring-1 ring-emerald-300/22 shadow-emerald-500/12',
        agent: 'ring-1 ring-amber-300/22 shadow-amber-500/12',
        code: 'ring-1 ring-violet-300/22 shadow-violet-500/12',
        research: 'ring-1 ring-cyan-300/22 shadow-cyan-500/12',
        business: 'ring-1 ring-emerald-200/22 shadow-emerald-500/10',
        recover: 'ring-1 ring-rose-300/24 shadow-rose-500/14',
      };
      return message.role === 'user' ? (userMap[key] || '') : (assistantMap[key] || '');
    },

    threadModeBadgeClass(message = {}) {
      const key = this.threadModeKey(message);
      const map = {
        ask: 'border-blue-500/20 bg-blue-500/10 text-blue-200',
        auto: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200',
        agent: 'border-amber-500/25 bg-amber-500/10 text-amber-200',
        code: 'border-violet-500/25 bg-violet-500/10 text-violet-200',
        research: 'border-cyan-500/25 bg-cyan-500/10 text-cyan-200',
        business: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-100',
        recover: 'border-rose-500/25 bg-rose-500/10 text-rose-200',
      };
      return map[key] || map.ask;
    },

    threadModeLabel(message = {}) {
      const key = this.threadModeKey(message);
      const map = {
        ask: 'Ask',
        auto: 'Auto',
        agent: 'Agent',
        code: 'Code',
        research: 'Research',
        business: 'Business',
        recover: 'Recover',
      };
      return map[key] || 'Ask';
    },

    threadModeIcon(message = {}) {
      return this.conversationModeIcon(this.threadModeKey(message));
    },

    pendingAgentApprovalKey(approval = null) {
      if (!approval || typeof approval !== 'object') return '';
      const kind = String(approval.kind || '').trim().toLowerCase();
      const sessionId = String(approval.sessionId || approval.session_id || '').trim();
      const fingerprint = String(
        approval.actionFingerprint
        || approval.action_fingerprint
        || approval.approvalAction?.action_fingerprint
        || ''
      ).trim();
      const path = String(approval.path || '').trim();
      const command = String(approval.command || '').trim();
      const fullCommand = String(approval.fullCommand || approval.full_command || '').trim();
      const action = String(approval.action || '').trim();
      return [sessionId, fingerprint, kind, action, path, command, fullCommand].join('|');
    },

    normalizePendingAgentApproval(approval = null, session = null) {
      if (!approval || typeof approval !== 'object') return null;
      const kind = String(approval.kind || '').trim().toLowerCase();
      if (!kind) return null;
      const approvalAction = (approval.approval_action || approval.approvalAction || null);
      const path = String(approval.path || '').trim();
      const action = String(approval.action || '').trim().toLowerCase() || 'edit';
      const command = String(approval.command || '').trim();
      const fullCommand = String(approval.full_command || approval.fullCommand || command).trim();
      const message = String(
        approval.message
        || (kind === 'edit'
          ? `Approval required before Axon can ${action} ${path || 'this file'}.`
          : `Approval required before Axon can run ${fullCommand || command || 'this command'}.`)
      ).trim();
      return {
        kind,
        action,
        path,
        command,
        fullCommand,
        message,
        approvalAction,
        actionFingerprint: String(
          approval.action_fingerprint
          || approval.actionFingerprint
          || approvalAction?.action_fingerprint
          || ''
        ).trim(),
        actionType: String(
          approval.action_type
          || approval.actionType
          || approvalAction?.action_type
          || ''
        ).trim(),
        summary: String(approval.summary || approvalAction?.summary || '').trim(),
        repoRoot: String(approval.repo_root || approvalAction?.repo_root || '').trim(),
        persistAllowed: !!(approval.persist_allowed ?? approvalAction?.persist_allowed),
        scopeOptions: Array.isArray(approval.scope_options || approvalAction?.scope_options)
          ? [...(approval.scope_options || approvalAction?.scope_options)]
          : ['once', 'task', 'session'],
        evidenceSource: String(approval.evidence_source || approvalAction?.evidence_source || '').trim(),
        task: String(session?.task || approval.task || '').trim(),
        workspaceId: String(session?.workspace_id || approval.workspace_id || this.chatProjectId || '').trim(),
        sessionId: String(session?.session_id || approval.session_id || '').trim(),
        resolved: '',
        resolutionMessage: '',
      };
    },

    syncPendingAgentApproval(approval = null, session = null) {
      const normalized = this.normalizePendingAgentApproval(approval, session);
      if (!normalized) {
        this.pendingAgentApproval = null;
        return null;
      }
      const current = this.pendingAgentApproval;
      if (current && this.pendingAgentApprovalKey(current) === this.pendingAgentApprovalKey(normalized)) {
        this.pendingAgentApproval = {
          ...current,
          ...normalized,
          resolved: current.resolved || '',
          resolutionMessage: current.resolutionMessage || '',
        };
      } else {
        this.pendingAgentApproval = normalized;
      }
      return this.pendingAgentApproval;
    },

    clearPendingAgentApproval() {
      this.pendingAgentApproval = null;
    },

    shouldPollInterruptedSession() {
      if (!this.authenticated) return false;
      if (this.activeTab === 'chat') return true;
      return !!(this.chatLoading || this.liveOperator?.active || this.pendingAgentApproval || this.interruptedSession);
    },

    startInterruptedSessionPolling() {
      if (this._interruptedSessionPollTimer) return;
      this._interruptedSessionPollTimer = setInterval(() => {
        if (!this.shouldPollInterruptedSession()) return;
        this.checkInterruptedSession({ silent: true });
      }, 2500);
    },

    markPendingAgentApprovalResolved(state = 'approved', detail = '') {
      if (!this.pendingAgentApproval) return;
      const status = String(state || 'approved').trim().toLowerCase();
      this.pendingAgentApproval = {
        ...this.pendingAgentApproval,
        resolved: status,
        resolutionMessage: String(detail || '').trim()
          || (status === 'denied'
            ? 'Permission denied. Axon will continue with safer alternatives.'
            : 'Permission granted. Axon is continuing the same task.'),
      };
    },

    prepareInterruptedSessionResume() {
      this.resumeBannerDismissed = true;
      this.removeInterruptedSessionMessages();
    },

    activePendingAgentApproval() {
      const approval = this.pendingAgentApproval;
      if (!approval) return null;
      const workspaceId = String(this.chatProjectId || '').trim();
      const approvalWorkspace = String(approval.workspaceId || '').trim();
      if (workspaceId && approvalWorkspace && workspaceId !== approvalWorkspace) return null;
      return approval;
    },

    agentApprovalSubject(approval = null) {
      const item = approval || this.activePendingAgentApproval();
      if (!item) return '';
      if (item.kind === 'command') return item.fullCommand || item.command || '';
      return item.path || '';
    },

    agentApprovalHint(approval = null) {
      const item = approval || this.activePendingAgentApproval();
      if (!item) return '';
      if (item.resolved) return item.resolutionMessage || '';
      const source = item.evidenceSource ? ` Source: ${item.evidenceSource.replace(/_/g, ' ')}.` : '';
      if (item.kind === 'command') {
        return `Approve the exact blocked action below so Axon can retry it safely.${source}`;
      }
      return `Approve the exact file action below so Axon can retry it safely.${source}`;
    },

    agentApprovalStatusLabel(approval = null) {
      const item = approval || this.activePendingAgentApproval();
      if (!item) return '';
      if (item.resolved === 'approved') return 'Allowed';
      if (item.resolved === 'denied') return 'Denied';
      return 'Awaiting approval';
    },

    agentApprovalStatusClass(approval = null) {
      const item = approval || this.activePendingAgentApproval();
      if (!item) return 'axon-approval-dock__status';
      if (item.resolved === 'approved') return 'axon-approval-dock__status axon-approval-dock__status--approved';
      if (item.resolved === 'denied') return 'axon-approval-dock__status axon-approval-dock__status--denied';
      return 'axon-approval-dock__status axon-approval-dock__status--pending';
    },

    normalizeEvidenceSource(value = '') {
      const raw = String(value || '').trim().toLowerCase();
      if (!raw) return '';
      if (raw === 'model_only') return 'model';
      if (raw === 'cached_external') return 'cached web';
      if (raw === 'live_external') return 'live web';
      return raw.replace(/_/g, ' ');
    },

    addMessageEvidenceSource(message, value = '') {
      const source = this.normalizeEvidenceSource(value);
      if (!source) return;
      if (!Array.isArray(message.evidenceSources)) message.evidenceSources = [];
      if (!message.evidenceSources.includes(source)) message.evidenceSources.push(source);
    },

    inferEvidenceSourceFromTool(name = '', result = '') {
      const tool = String(name || '').trim().toLowerCase();
      const text = String(result || '');
      if (tool === 'http_get') {
        if (text.includes('[cache hit]')) return 'cached web';
        if (text.includes('[live fetch]')) return 'live web';
      }
      if (tool.startsWith('memory_') || tool === 'recall' || tool === 'remember') return 'memory';
      if (tool === 'read_file' || tool === 'list_dir' || tool === 'show_diff' || tool === 'git_status') return 'workspace';
      if (tool === 'shell_cmd' || tool === 'shell_bg' || tool === 'shell_bg_check') return 'workspace';
      if (tool === 'generate_image') return 'resource';
      return '';
    },

    workingTitleForEvent(event = {}) {
      const tool = String(event.name || '').trim().toLowerCase();
      const args = event.args || {};
      const command = String(args.cmd || '').trim().toLowerCase();
      if (tool === 'shell_cmd') {
        if (/\b(test|jest|vitest|pytest|cargo test|go test|npm test|pnpm test|yarn test)\b/.test(command)) return 'Running tests';
        if (/\b(build|compile|typecheck|tsc|lint)\b/.test(command)) return 'Verifying changes';
        if (command.startsWith('git status')) return 'Checking git status';
        if (command.startsWith('git add')) return 'Staging changes';
        if (command.startsWith('git commit')) return 'Creating commit';
        if (command.startsWith('git push')) return 'Pushing branch';
        if (command.startsWith('gh pr')) return 'Updating pull request';
      }
      if (tool === 'http_get') return 'Fetching web page';
      if (tool === 'read_file') return 'Reading file';
      if (tool === 'list_dir') return 'Listing workspace files';
      if (tool === 'write_file' || tool === 'edit_file' || tool === 'append_file' || tool === 'create_file') return 'Applying file change';
      if (tool === 'git_status') return 'Checking git status';
      return `Working · ${this.prettyToolName(event.name)}`;
    },

    thinkingTitleFor(text = '') {
      const sample = String(text || '').toLowerCase();
      if (!sample) return 'Thinking';
      if (sample.includes('memory')) return 'Using memory';
      if (sample.includes('cache')) return 'Using cache';
      if (sample.includes('test')) return 'Running tests';
      if (sample.includes('approval')) return 'Awaiting approval';
      if (sample.includes('final') || sample.includes('wrap') || sample.includes('answer')) return 'Finalizing';
      if (sample.includes('route') || sample.includes('router')) return 'Routing';
      if (sample.includes('inspect') || sample.includes('scan') || sample.includes('read')) return 'Inspecting';
      return 'Thinking';
    },

    messageShowsWorkingSpinner(message = {}) {
      const autoSessionId = String(message?.autoSessionId || '').trim();
      if (message?.autoSessionNotice && autoSessionId) {
        const session = (this.autoSessions || []).find(item => String(item?.session_id || '') === autoSessionId);
        return String(session?.status || '') === 'running';
      }
      const hasRunningWorking = Array.isArray(message?.workingBlocks) && message.workingBlocks.some(block => String(block?.status || 'running') === 'running');
      if (hasRunningWorking) return true;
      const hasRunningThinking = Array.isArray(message?.thinkingBlocks) && message.thinkingBlocks.some(block => String(block?.status || 'running') === 'running');
      if (hasRunningThinking) return true;
      const lastMessageId = this.chatMessages?.length ? this.chatMessages[this.chatMessages.length - 1]?.id : null;
      return !!(this.chatLoading && message?.role === 'assistant' && lastMessageId && String(lastMessageId) === String(message?.id || ''));
    },

    messageWorkingLabel(message = {}) {
      if (message?.autoSessionNotice) return 'Working on it';
      return 'Working';
    },

    preferredResumeAutoSession(message = '', source = 'resume') {
      const explicit = this.isExplicitResumeText(message)
        || ['retry_button', 'resume_banner', 'approval_continue', 'typed_continue', 'quick_resume'].includes(String(source || '').trim().toLowerCase());
      if (!explicit) return null;
      return this.currentWorkspaceAutoSession() || this.activeAutoSession() || null;
    },

    hasExplicitResumeTarget(payload = {}) {
      if (!payload || typeof payload !== 'object') return false;
      return !!String(payload.resume_session_id || payload.continue_task || '').trim();
    },

    clarificationQuestionFor(msg = '', requestedMode = '') {
      const text = String(msg || '').trim();
      if (!text) return '';
      const lower = text.toLowerCase();
      const effectiveMode = requestedMode || this.effectiveChatMode(text);
      const actionable = effectiveMode === 'agent' || this.shouldAutoUseAgent(text);
      if (!actionable) return '';

      const hasWorkspace = !!this.chatProjectId;
      const hasInterruptedSession = !!this.interruptedSession;
      const pronounTargetOnly = /^(please\s+)?(continue|fix|check|scan|run|open|review|inspect|look at|work on|do|update|change|build|deploy|test|read|write)\s+(it|this|that|there|here)\b/i.test(text);
      const bareContinue = /^(please\s+)?continue\b[.!?]*$/i.test(text);
      const workspaceIntent = /\b(project|repo|repository|workspace|codebase|scan|inspect|fix|run|build|deploy|test)\b/i.test(lower);

      // "continue" / "please continue" always goes to the server —
      // the backend session store decides whether there's something to resume.
      if (bareContinue) return '';
      if (pronounTargetOnly) {
        return 'What should I apply that to? Give me the workspace, file, repo, branch, or task target and I will continue.';
      }
      if (!hasWorkspace && workspaceIntent) {
        return 'Which workspace should I use for that? Pick one in the workspace selector or name the project first.';
      }
      return '';
    },

    addLocalClarificationExchange(msg, question, mode, resources = []) {
      const createdAt = new Date().toISOString();
      const threadMode = this.currentThreadMode(mode);
      this.chatMessages.push({
        id: Date.now(),
        role: 'user',
        content: msg,
        created_at: createdAt,
        mode,
        threadMode,
        resources,
      });
      this.chatMessages.push({
        id: Date.now() + 1,
        role: 'assistant',
        content: question,
        created_at: new Date().toISOString(),
        mode: 'chat',
        threadMode,
        resources: [],
      });
      this.scrollChat(true);
    },

    /* ── Business mode ────────────────────────────────────────── */

    toggleBusinessMode(force = null) {
      const enabled = typeof force === 'boolean' ? force : !this.businessMode;
      if (enabled) {
        this.resetPrimaryConversationModes();
        this.businessMode = true;
        this.composerOptions.intelligence_mode = 'build_brief';
        this.composerOptions.action_mode = 'generate';
      } else {
        this.setConversationModeAsk();
      }
      this.persistConversationModePreference();
    },

    setBusinessView(view) {
      this.businessView = view;
      this.businessDraft.docType =
        view === 'quote' ? 'quote'
        : view === 'receipt' ? 'receipt'
        : view === 'client' ? 'client'
        : 'invoice';
    },

    addBusinessItem() {
      this.businessDraft.items.push({
        description: '',
        qty: 1,
        rate: 0,
      });
    },

    removeBusinessItem(index) {
      this.businessDraft.items.splice(index, 1);
    },

    businessSubtotal() {
      return (this.businessDraft.items || []).reduce((sum, item) => {
        const qty = Number(item.qty || 0);
        const rate = Number(item.rate || 0);
        return sum + (qty * rate);
      }, 0);
    },

    businessDiscountAmount() {
      const subtotal = this.businessSubtotal();
      const value = Number(this.businessDraft.discountValue || 0);
      if (this.businessDraft.discountType === 'percent') {
        return subtotal * (value / 100);
      }
      return value;
    },

    businessTotal() {
      return Math.max(0, this.businessSubtotal() - this.businessDiscountAmount());
    },

    formatMoney(amount) {
      const value = Number(amount || 0);
      return new Intl.NumberFormat('en-ZA', {
        style: 'currency',
        currency: this.businessDraft.currency || 'ZAR',
      }).format(value);
    },

    businessComposerPrompt(type = 'invoice') {
      const client = this.businessDraft.client.name || 'the client';
      const subtotal = this.businessSubtotal();
      const discount = this.businessDiscountAmount();
      const total = this.businessTotal();
      const lines = (this.businessDraft.items || [])
        .map(i => `- ${i.description || 'Item'} | qty ${i.qty || 1} | rate ${i.rate || 0}`)
        .join('\n');

      return [
        `Create a professional ${type} for ${client}.`,
        `Currency: ${this.businessDraft.currency}.`,
        `Issue date: ${this.businessDraft.issueDate || 'not set'}.`,
        `Due date: ${this.businessDraft.dueDate || 'not set'}.`,
        `Client email: ${this.businessDraft.client.email || 'not provided'}.`,
        `Line items:`,
        lines || '- No items yet',
        `Subtotal: ${subtotal}`,
        `Discount: ${discount}`,
        `Total: ${total}`,
        `Include a clean client-ready breakdown, summary, and payment wording.`,
      ].join('\n');
    },

    injectBusinessPrompt(type = 'invoice') {
      this.setBusinessView(type);
      this.businessMode = true;
      this.chatInput = this.businessComposerPrompt(type);
      if (typeof this.resetChatComposerHeight === 'function') {
        this.resetChatComposerHeight();
      }
      if (typeof this.showToast === 'function') {
        this.showToast(`${type.charAt(0).toUpperCase() + type.slice(1)} draft loaded into composer`);
      }
    },

    /* ── Live operator ────────────────────────────────────────── */

    beginLiveOperator(mode, msg = '') {
      if (this.liveOperatorTimer) clearTimeout(this.liveOperatorTimer);
      this.liveOperator = {
        active: true,
        mode,
        phase: mode === 'agent' ? 'observe' : 'plan',
        title: mode === 'agent' ? 'Observing the task' : 'Opening the reply stream',
        detail: mode === 'agent'
          ? 'Axon is checking your goal and lining up the first safe step.'
          : 'Axon is preparing a response.',
        tool: '',
        startedAt: new Date().toISOString(),
        workspaceId: String(this.chatProjectId || '').trim(),
        autoSessionId: '',
        updatedAt: new Date().toISOString(),
      };
      this.liveOperatorFeed = [];
      this.pushLiveOperatorFeed(
        this.liveOperator.phase,
        this.liveOperator.title,
        msg ? `Goal received: ${msg.slice(0, 120)}` : this.liveOperator.detail,
      );
      if (mode === 'agent') { this.setAgentStage('observe'); this.agentCtxPct = 0; this.agentCtxIter = 0; }
      if (this.desktopPreview.enabled) {
        this.refreshDesktopPreview(true);
        this.scheduleDesktopPreview();
      }
    },

    updateLiveOperator(mode, event = {}) {
      if (!this.liveOperator.active) this.beginLiveOperator(mode);
      const updatedAt = new Date().toISOString();
      const workspaceId = String(this.liveOperator.workspaceId || this.chatProjectId || '').trim();
      if (mode !== 'agent') {
        if (event.error) {
          this.liveOperator = {
            ...this.liveOperator,
            active: true,
            phase: 'recover',
            title: 'Reply interrupted',
            detail: event.error,
            workspaceId,
            updatedAt,
          };
          this.pushLiveOperatorFeed('recover', 'Reply interrupted', event.error);
          return;
        }
        if (event.done) {
          this.liveOperator = {
            ...this.liveOperator,
            active: true,
            phase: 'verify',
            title: 'Reply complete',
            detail: 'Axon finished streaming the answer.',
            workspaceId,
            updatedAt,
          };
          this.pushLiveOperatorFeed('verify', 'Reply complete', 'Axon finished streaming the answer.');
          return;
        }
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'execute',
          title: 'Writing the reply',
          detail: 'Live response is flowing into the console now.',
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed('execute', 'Writing the reply', 'Live response is flowing into the console now.');
        return;
      }

      if (event.type === 'tool_call') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'execute',
          title: `Running ${this.prettyToolName(event.name)}`,
          detail: event.args ? JSON.stringify(event.args).slice(0, 96) : 'Using a local operator tool.',
          tool: event.name || '',
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed('execute', `Running ${this.prettyToolName(event.name)}`, event.args ? JSON.stringify(event.args).slice(0, 96) : 'Using a local operator tool.');
        // Mirror shell commands to the integrated terminal
        if ((event.name === 'shell_cmd' || event.name === 'shell_bg') && event.args?.cmd) {
          this._mirrorShellToTerminal(event.args.cmd, event.args.cwd);
        }
        return;
      }
      if (event.type === 'tool_result') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'verify',
          title: `Checking ${this.prettyToolName(event.name)}`,
          detail: (event.result || 'Axon is reviewing the tool output.').slice(0, 120),
          tool: event.name || this.liveOperator.tool,
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed('verify', `Checking ${this.prettyToolName(event.name)}`, (event.result || 'Axon is reviewing the tool output.').slice(0, 120));
        // Mirror shell output to the integrated terminal
        if ((event.name === 'shell_cmd' || event.name === 'shell_bg' || event.name === 'shell_bg_check') && event.result) {
          this._mirrorShellResultToTerminal(event.result);
        }
        // Auto-detect dev server URL from shell_bg output
        if ((event.name === 'shell_bg' || event.name === 'shell_bg_check') && event.result) {
          this._detectDevServerUrl(event.result);
        }
        return;
      }
      if (event.type === 'text') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: this.liveOperator.tool ? 'verify' : 'plan',
          title: this.liveOperator.tool ? 'Writing the result' : 'Planning the next step',
          detail: this.liveOperator.tool
            ? 'Axon is turning tool output into a final answer.'
            : 'Axon is reasoning through the task before it acts.',
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed(
          this.liveOperator.tool ? 'verify' : 'plan',
          this.liveOperator.tool ? 'Writing the result' : 'Planning the next step',
          this.liveOperator.tool
            ? 'Axon is turning tool output into a final answer.'
            : 'Axon is reasoning through the task before it acts.',
        );
        return;
      }
      if (event.type === 'done') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'verify',
          title: 'Task complete',
          detail: 'Axon finished the operator pass.',
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed('verify', 'Task complete', 'Axon finished the operator pass.');
        return;
      }
      if (event.type === 'error') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'recover',
          title: 'Needs attention',
          detail: event.message || 'Axon hit an error and stopped safely.',
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed('recover', 'Needs attention', event.message || 'Axon hit an error and stopped safely.');
        return;
      }
      if (event.type === 'approval_required') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'recover',
          title: 'Awaiting approval',
          detail: event.message || 'Axon paused until you approve or deny the blocked action.',
          workspaceId,
          updatedAt,
        };
        this.pushLiveOperatorFeed('recover', 'Awaiting approval', event.message || 'Axon paused until you approve or deny the blocked action.');
      }
    },

    syncLiveOperatorFromSnapshot(snapshot = {}) {
      if (!snapshot || typeof snapshot !== 'object') return;
      const active = !!snapshot.active;
      if (!active) {
        if (!this.chatLoading) this.clearLiveOperator(0);
        return;
      }
      const workspaceId = String(snapshot.workspace_id || this.liveOperator.workspaceId || '').trim();
      if (workspaceId) this.ensureWorkspaceTab?.(workspaceId);
      const autoSessionId = String(snapshot.auto_session_id || this.liveOperator.autoSessionId || '').trim();
      this.liveOperator = {
        ...this.liveOperator,
        active: true,
        mode: snapshot.mode || this.liveOperator.mode || 'chat',
        phase: snapshot.phase || this.liveOperator.phase || 'observe',
        title: snapshot.title || this.liveOperator.title || 'Axon is working…',
        detail: snapshot.detail || snapshot.summary || this.liveOperator.detail || '',
        tool: snapshot.tool || this.liveOperator.tool || '',
        startedAt: snapshot.started_at || this.liveOperator.startedAt || '',
        workspaceId,
        autoSessionId,
        updatedAt: snapshot.updated_at || this.liveOperator.updatedAt || new Date().toISOString(),
      };
      if (Array.isArray(snapshot.feed) && snapshot.feed.length) {
        this.liveOperatorFeed = snapshot.feed.slice(-6).map(entry => ({
          id: String(entry?.id || `${entry?.at || Date.now()}-${entry?.phase || 'observe'}`),
          phase: String(entry?.phase || 'observe'),
          title: String(entry?.title || 'Working'),
          detail: String(entry?.detail || ''),
          at: String(entry?.at || new Date().toISOString()),
        }));
      }
      this.syncAutoSessionNoticeForCurrentWorkspace?.();
    },

    liveOperatorWorkspaceName() {
      const workspaceId = String(this.liveOperator?.workspaceId || '').trim();
      if (!workspaceId) return '';
      return this.workspaceTabLabel?.(workspaceId) || this.chatProject?.name || `Workspace ${workspaceId}`;
    },

    canFollowLiveWorkspace() {
      const workspaceId = String(this.liveOperator?.workspaceId || '').trim();
      if (!workspaceId) return false;
      if (String(this.chatProjectId || '').trim() === workspaceId) return false;
      return (this.projects || []).some(project => String(project.id) === workspaceId);
    },

    followLiveWorkspace() {
      const workspaceId = String(this.liveOperator?.workspaceId || '').trim();
      if (!workspaceId) return;
      this.activeTab = 'chat';
      this.activateWorkspaceTab?.(workspaceId);
      this.showConsoleDetails = false;
      this.showToast?.(`Following ${this.liveOperatorWorkspaceName()}`);
    },

    clearLiveOperator(delay = 0) {
      if (this.liveOperatorTimer) clearTimeout(this.liveOperatorTimer);
      const reset = () => {
        this.liveOperator = {
          active: false,
          mode: 'chat',
          phase: 'observe',
          title: '',
          detail: '',
          tool: '',
          startedAt: '',
          workspaceId: '',
          autoSessionId: '',
          updatedAt: '',
        };
        this.stopDesktopPreview();
      };
      if (delay > 0) {
        this.liveOperatorTimer = setTimeout(reset, delay);
      } else {
        reset();
      }
    },

    rememberOperatorOutcome(mode, message) {
      const content = String(message?.content || '').replace(/\s+/g, ' ').trim();
      const latestEvent = [...(message?.agentEvents || [])].reverse()
        .find(ev => ev.type === 'tool_result' || ev.type === 'tool_call');
      this.lastOperatorOutcome = {
        title: mode === 'agent' ? 'Axon finished this task' : 'Axon finished the reply',
        summary: (content || latestEvent?.result || 'Completed.').slice(0, 180),
        tool: latestEvent?.name || '',
        at: new Date().toISOString(),
      };
    },

    ensureAssistantMessageBlocks(message) {
      if (!message) return;
      if (!Array.isArray(message.thinkingBlocks)) message.thinkingBlocks = [];
      if (!Array.isArray(message.workingBlocks)) message.workingBlocks = [];
      if (!Number.isInteger(message.agentBlockCounter)) {
        const existingOrders = [...message.thinkingBlocks, ...message.workingBlocks]
          .map(block => Number(block?.order || 0))
          .filter(order => Number.isFinite(order) && order > 0);
        message.agentBlockCounter = existingOrders.length ? Math.max(...existingOrders) : 0;
      }
      if (!message.providerIdentity) message.providerIdentity = this.assistantProviderIdentity();
    },

    nextAgentBlockOrder(message) {
      this.ensureAssistantMessageBlocks(message);
      message.agentBlockCounter += 1;
      return message.agentBlockCounter;
    },

    chronologicalAgentBlocks(message) {
      this.ensureAssistantMessageBlocks(message);
      const blocks = [
        ...(message.thinkingBlocks || []).map(block => ({ kind: 'thinking', block })),
        ...(message.workingBlocks || []).map(block => ({ kind: 'working', block })),
      ].sort((left, right) => {
        const orderDelta = Number(left.block?.order || 0) - Number(right.block?.order || 0);
        if (orderDelta !== 0) return orderDelta;
        return String(left.block?.createdAt || '').localeCompare(String(right.block?.createdAt || ''));
      });
      let stepNum = 0;
      for (const entry of blocks) {
        if (entry.kind === 'working') entry.stepNum = ++stepNum;
      }
      return blocks;
    },

    appendThinkingBlock(message, chunk) {
      const text = String(chunk || '');
      if (!text.trim()) return;
      this.ensureAssistantMessageBlocks(message);
      const last = message.thinkingBlocks[message.thinkingBlocks.length - 1];
      if (last && last.status === 'active') {
        // Append directly — the server handles spacing normalisation via
        // _normalize_thinking_spacing() in agent_output.py. Do NOT insert
        // spaces here: streaming providers like DeepSeek emit sub-word
        // tokens (individual characters), and injecting spaces between them
        // creates the "N o w I h a v e" broken-word artefact.
        last.content += text;
        last.title = this.thinkingTitleFor(last.content);
        last.updatedAt = new Date().toISOString();
        return;
      }
      message.thinkingBlocks.push({
        id: `think-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        title: this.thinkingTitleFor(text),
        content: text,
        status: 'active',
        order: this.nextAgentBlockOrder(message),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
    },

    finalizeThinkingBlocks(message) {
      this.ensureAssistantMessageBlocks(message);
      message.thinkingBlocks.forEach(block => {
        if (block.status === 'active') block.status = 'done';
      });
    },

    appendWorkingBlock(message, event) {
      this.ensureAssistantMessageBlocks(message);
      const evidenceSource = this.normalizeEvidenceSource(event.evidence_source || this.inferEvidenceSourceFromTool(event.name, event.result));
      message.workingBlocks.push({
        id: `work-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: event.name || '',
        title: this.workingTitleForEvent(event),
        args: event.args || {},
        result: '',
        evidenceSource,
        status: 'running',
        order: this.nextAgentBlockOrder(message),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
      this.addMessageEvidenceSource(message, evidenceSource);
    },

    resolveWorkingBlock(message, event) {
      this.ensureAssistantMessageBlocks(message);
      const evidenceSource = this.normalizeEvidenceSource(event.evidence_source || this.inferEvidenceSourceFromTool(event.name, event.result));
      const match = [...message.workingBlocks].reverse().find(block => block.name === event.name && block.status === 'running');
      if (match) {
        match.status = 'done';
        match.result = String(event.result || '').trim();
        match.evidenceSource = evidenceSource || match.evidenceSource || '';
        match.updatedAt = new Date().toISOString();
        this.addMessageEvidenceSource(message, match.evidenceSource);
        return;
      }
      message.workingBlocks.push({
        id: `work-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: event.name || '',
        title: this.workingTitleForEvent(event),
        args: {},
        result: String(event.result || '').trim(),
        evidenceSource,
        status: 'done',
        order: this.nextAgentBlockOrder(message),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
      this.addMessageEvidenceSource(message, evidenceSource);
    },

    finalizeWorkingBlocks(message) {
      this.ensureAssistantMessageBlocks(message);
      message.workingBlocks.forEach(block => {
        if (block.status === 'running') {
          block.status = 'done';
          block.updatedAt = new Date().toISOString();
        }
      });
    },

    /* ── Streaming ────────────────────────────────────────────── */

    createAssistantPlaceholder(respId, mode, retryResources = []) {
      const providerIdentity = this.assistantProviderIdentity();
      return {
        id: respId,
        role: 'assistant',
        content: '',
        streaming: true,
        created_at: new Date().toISOString(),
        mode,
        threadMode: this.currentThreadMode(mode),
        modelLabel: providerIdentity.modelLabel || this.assistantRuntimeLabel(),
        providerIdentity,
        thinkingBlocks: [],
        workingBlocks: [],
        agentEvents: mode === 'agent' ? [] : undefined,
        evidenceSources: [],
        resources: [],
        retryResources,
      };
    },

    extractGeneratedResource(resultText) {
      const text = String(resultText || '');
      const idMatch = text.match(/resource\s+#(\d+)/i);
      if (!idMatch) return null;
      const titleMatch = text.match(/resource\s+#\d+\s*:\s*([^\n]+)/i);
      return {
        id: Number(idMatch[1]),
        kind: 'image',
        title: (titleMatch?.[1] || 'Generated image').trim(),
      };
    },

    attachGeneratedResource(message, resultText) {
      const resource = this.extractGeneratedResource(resultText);
      if (!resource) return;
      if (!Array.isArray(message.resources)) message.resources = [];
      if (message.resources.some(item => Number(item?.id) === resource.id)) return;
      message.resources.push(resource);
    },

    stopGeneration() {
      if (this._chatAbortController) {
        this._chatAbortController.abort();
        this._chatAbortController = null;
      }
      // Mark all streaming messages as done
      this.chatMessages.forEach(m => {
        if (m.streaming) m.streaming = false;
      });
      this.chatLoading = false;
      this.clearLiveOperator(400);
      this.showToast('Generation stopped');
    },

    async streamChatMessage(msg, mode, respId, resourceIds = [], extraPayload = {}) {
      const needsLocalTools = this.shouldAutoUseAgent(msg);
      let effectiveMode = this.effectiveChatMode(msg, mode);
      if (effectiveMode === 'chat' && needsLocalTools && !this.currentBackendSupportsAgent()) {
        this.updateLiveOperator('chat', {
          type: 'error',
          message: 'This request needs local tools, but the current runtime cannot execute operator actions.',
        });
        throw new Error('This request needs local tools. Switch to an agent-capable runtime to run it safely.');
      }

      const endpoint = effectiveMode === 'agent' ? '/api/agent' : '/api/chat/stream';
      const payload = {
        message: msg,
        project_id: this.chatProjectId ? parseInt(this.chatProjectId) : null,
        resource_ids: resourceIds,
        composer_options: this.normalizedComposerOptions(),
        ...extraPayload,
      };
      if (this.usesOllamaBackend()) payload.model = this.activeChatModel() || '';

      this._chatAbortController = new AbortController();
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: this.authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
        signal: this._chatAbortController.signal,
      });

      if (resp.status === 401) {
        this.handleAuthRequired();
        this.updateLiveOperator(mode, { type: 'error', message: 'Session expired.' });
        throw new Error('Session expired');
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        this.updateLiveOperator(mode, { type: 'error', message: err.detail || resp.statusText });
        throw new Error(err.detail || resp.statusText);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      if (effectiveMode === 'agent') {
        this.setAgentStage('plan');
        this.updateLiveOperator(effectiveMode, { type: 'text' });
      } else {
        this.updateLiveOperator(effectiveMode, { chunk: 'stream-open' });
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            const idx = this.chatMessages.findIndex(m => m.id === respId);
            if (idx < 0) continue;
            this.ensureAssistantMessageBlocks(this.chatMessages[idx]);

            if (effectiveMode === 'agent') {
              if (data.type === 'thinking') {
                this.clearPendingAgentApproval();
                this.setAgentStage('plan');
                this.appendThinkingBlock(this.chatMessages[idx], data.chunk);
                this.updateLiveOperator(effectiveMode, { type: 'text' });
                this.scrollChat();
              } else if (data.type === 'text') {
                this.clearPendingAgentApproval();
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                if (this.chatMessages[idx].agentEvents?.length) this.setAgentStage('verify');
                this.chatMessages[idx].content += data.chunk;
                this.addMessageEvidenceSource(this.chatMessages[idx], data.evidence_source || data.evidenceSource || '');
                this.updateLiveOperator(effectiveMode, data);
                this.scrollChat();
              } else if (data.type === 'tool_call' || data.type === 'tool_result') {
                this.clearPendingAgentApproval();
                this.setAgentStage(data.type === 'tool_call' ? 'execute' : 'verify');
                this.chatMessages[idx].agentEvents.push(data);
                if (data.type === 'tool_call') {
                  this.finalizeThinkingBlocks(this.chatMessages[idx]);
                  this.appendWorkingBlock(this.chatMessages[idx], data);
                } else {
                  this.resolveWorkingBlock(this.chatMessages[idx], data);
                  if (data.name === 'generate_image') {
                    this.attachGeneratedResource(this.chatMessages[idx], data.result);
                  }
                }
                this.updateLiveOperator(effectiveMode, data);
                this.scrollChat();
              } else if (data.type === 'context_usage') {
                this.agentCtxPct = data.pct || 0;
                this.agentCtxIter = data.iteration || 0;
                this.agentMaxIter = data.max_iterations || this.agentMaxIter || 75;
              } else if (data.type === 'done') {
                this.clearPendingAgentApproval();
                this.setAgentStage('verify');
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                this.finalizeWorkingBlocks(this.chatMessages[idx]);
                this.chatMessages[idx].streaming = false;
                // Auto-speak response if voice mode is active
                if (typeof this.autoSpeakResponse === 'function') {
                  this.autoSpeakResponse(this.chatMessages[idx].content);
                }
                this.updateLiveOperator(effectiveMode, data);
              } else if (data.type === 'error') {
                this.clearPendingAgentApproval();
                this.setAgentStage('recover');
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                this.finalizeWorkingBlocks(this.chatMessages[idx]);
                this.chatMessages[idx].content += `\n⚠️ ${data.message}`;
                this.chatMessages[idx].streaming = false;
                this.chatMessages[idx].error = true;
                this.chatMessages[idx].retryMsg = msg;
                this.updateLiveOperator(effectiveMode, data);
              } else if (data.type === 'approval_required') {
                this.setAgentStage('recover');
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                this.finalizeWorkingBlocks(this.chatMessages[idx]);
                this.chatMessages[idx].streaming = false;
                this.chatMessages[idx].pendingApproval = data;
                this.syncPendingAgentApproval(data);
                this.updateLiveOperator(effectiveMode, data);
                this.checkInterruptedSession();
                this.showToast(data.message || 'Approval required to continue this task');
              }
            } else {
              if (data.chunk) {
                this.chatMessages[idx].content += data.chunk;
                this.addMessageEvidenceSource(this.chatMessages[idx], data.evidence_source || data.evidenceSource || '');
                this.updateLiveOperator(effectiveMode, data);
                this.scrollChat();
              }
              if (data.done) {
                this.chatMessages[idx].streaming = false;
                // Auto-speak response if voice mode is active
                if (typeof this.autoSpeakResponse === 'function') {
                  this.autoSpeakResponse(this.chatMessages[idx].content);
                }
                this.updateLiveOperator(effectiveMode, data);
              }
              if (data.error) {
                this.chatMessages[idx].content += `\n⚠️ ${data.error}`;
                this.chatMessages[idx].streaming = false;
                this.chatMessages[idx].error = true;
                this.chatMessages[idx].retryMsg = msg;
                this.updateLiveOperator(mode, { error: data.error });
              }
            }
          } catch(_) {}
        }
      }

      this._chatAbortController = null;
      const idx = this.chatMessages.findIndex(m => m.id === respId);
      if (idx >= 0) {
        this.finalizeThinkingBlocks(this.chatMessages[idx]);
        this.finalizeWorkingBlocks(this.chatMessages[idx]);
        this.chatMessages[idx].streaming = false;
        // Mark as error if response is empty or only contains a warning
        const trimmed = (this.chatMessages[idx].content || '').trim();
        if ((!trimmed || /^⚠️?\s*(Empty response|error)/i.test(trimmed)) && !this.chatMessages[idx].pendingApproval) {
          this.chatMessages[idx].error = true;
          this.chatMessages[idx].retryMsg = msg;
          if (!trimmed) this.chatMessages[idx].content = '⚠️ Empty response from model.';
        }
        this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
        // Detect mission creation in response and trigger notification
        this._checkMissionNotification(this.chatMessages[idx].content);
        // Detect playbook creation in response and trigger notification
        this._checkPlaybookNotification(this.chatMessages[idx].content);
        // Generate follow-up suggestion chips
        this._generateFollowUpSuggestions(this.chatMessages[idx].content, msg);
      }
      this.clearLiveOperator(this.liveOperator.phase === 'recover' ? 4200 : 1400);
    },

    _generateFollowUpSuggestions(response, userMessage) {
      const suggestions = [];
      const lower = response.toLowerCase();
      const userLower = (userMessage || '').toLowerCase();
      const trimmed = response.trim();

      // Detect model asking for continuation ("Continue.", "please continue", etc.)
      if (/\bcontinue\.?\s*$/i.test(trimmed) || /\bplease continue\b/i.test(trimmed)) {
        suggestions.push('→ Continue');
      }

      // Context-aware suggestions based on response content
      if (/\b(created|saved|added)\b.{0,30}\b(mission|task)/i.test(response)) {
        suggestions.push('Show my active missions');
      }
      if (/\b(created|saved|added)\b.{0,30}\b(playbook|prompt)/i.test(response)) {
        suggestions.push('Open playbooks');
      }
      if (/```[\s\S]{20,}```/.test(response)) {
        suggestions.push('Explain this code');
        suggestions.push('Optimize this code');
      }
      if (/\b(plan|roadmap|strategy|steps?)\b/i.test(response) && suggestions.length < 3) {
        suggestions.push('Turn this into missions');
      }
      if (/\b(error|bug|issue|fix)\b/i.test(lower) && suggestions.length < 3) {
        suggestions.push('How do I debug this?');
      }
      if (/\b(api|endpoint|route)\b/i.test(lower) && suggestions.length < 3) {
        suggestions.push('Show example request');
      }

      // Generic fallbacks — always offer at least 2
      if (suggestions.length === 0) {
        suggestions.push('Tell me more');
        suggestions.push('What should I do next?');
      } else if (suggestions.length === 1) {
        suggestions.push('What should I do next?');
      }

      this.followUpSuggestions = suggestions.slice(0, 3);
    },

    useSuggestion(text) {
      this.followUpSuggestions = [];
      // "→ Continue" chip sends a continuation prompt
      const msg = text === '→ Continue' ? 'please continue' : text;
      this.chatInput = msg;
      this.$nextTick(() => this.sendChat());
    },

    /* ── Chat CRUD ────────────────────────────────────────────── */

    async loadChatHistory() {
      const scopeKey = String(this.chatProjectId || '').trim() || 'all';
      const requestSeq = Number(this._chatHistoryRequestSeq || 0) + 1;
      const scopeChanged = this._chatHistoryScopeKey !== scopeKey;
      this._chatHistoryRequestSeq = requestSeq;
      this._chatHistoryScopeKey = scopeKey;
      if (scopeChanged) {
        this.chatMessages = [];
        this.interruptedSession = null;
        this.pendingAgentApproval = null;
        this.resumeBannerDismissed = false;
      }
      try {
        const pid = this.chatProjectId ? `?project_id=${this.chatProjectId}&limit=40` : '?limit=40';
        const rows = await this.api('GET', `/api/chat/history${pid}`);
        if (requestSeq !== this._chatHistoryRequestSeq || this._chatHistoryScopeKey !== scopeKey) return;
        this.chatMessages = rows.map(r => {
          const parsed = this.parseStoredChatMessage(r.content);
          const resources = Array.isArray(r.resources) && r.resources.length ? r.resources : parsed.resources;
          const threadMode = String(r.thread_mode || parsed.threadMode || '').trim().toLowerCase();
          const mode = String(r.mode || parsed.mode || '').trim().toLowerCase()
            || (['agent', 'auto'].includes(threadMode) ? 'agent' : 'chat');
          return {
            id: r.created_at + r.role,
            role: r.role,
            content: parsed.content,
            created_at: r.created_at,
            mode,
            threadMode: threadMode || (mode === 'agent' ? 'agent' : 'ask'),
            modelLabel: r.model_label || parsed.modelLabel || '',
            resources,
          };
        });
        // Use requestAnimationFrame to ensure DOM is rendered and visible before scrolling
        this.$nextTick(() => {
          requestAnimationFrame(() => this.scrollChat(true));
        });
      } catch(e) {
        if (requestSeq !== this._chatHistoryRequestSeq || this._chatHistoryScopeKey !== scopeKey) return;
        this.chatMessages = [];
      }
      // Check for interrupted agent sessions on every chat load
      this.startInterruptedSessionPolling();
      this.checkInterruptedSession();
    },

    async checkInterruptedSession(options = {}) {
      if (this._interruptedSessionLoading) return;
      this._interruptedSessionLoading = true;
      const scopeKey = String(this.chatProjectId || '').trim() || 'all';
      const requestSeq = Number(this._interruptedSessionRequestSeq || 0) + 1;
      this._interruptedSessionRequestSeq = requestSeq;
      try {
        const params = this.chatProjectId ? `?project_id=${encodeURIComponent(this.chatProjectId)}` : '';
        const data = await this.api('GET', `/api/agent/sessions/interrupted${params}`);
        if (requestSeq !== this._interruptedSessionRequestSeq || this._chatHistoryScopeKey !== scopeKey) return;
        this.interruptedSession = data.session || null;
        if (this.interruptedSession?.status === 'approval_required') {
          this.syncPendingAgentApproval(this.interruptedSession.approval || { message: this.interruptedSession.last_error || '' }, this.interruptedSession);
        } else {
          this.clearPendingAgentApproval();
        }
        this.resumeBannerDismissed = false;
        this.injectInterruptedSessionMessage();
      } catch(e) {
        if (requestSeq !== this._interruptedSessionRequestSeq || this._chatHistoryScopeKey !== scopeKey) return;
        this.interruptedSession = null;
        this.clearPendingAgentApproval();
        this.removeInterruptedSessionMessages();
      } finally {
        this._interruptedSessionLoading = false;
      }
    },

    interruptedSessionMessageContent(session) {
      if (!session) return '';
      const task = session.task || 'Previous task';
      const assistant = String(session.last_assistant_message || '').trim();
      const error = String(session.error_message || '').trim();
      if (assistant) return assistant;
      if (session.status === 'approval_required') {
        const approval = session.approval || {};
        const detail = approval.message || 'Approval is required before Axon can continue this task.';
        return `⚠️ ${detail}\n\nTask: **${task}**`;
      }
      if (error) {
        return `⚠️ Agent error: ${error}\n\nTask: **${task}**\n\nReload restored the paused session. Use **Resume** or say **please continue** to continue from here.`;
      }
      return `⚠️ This agent session was interrupted before it finished.\n\nTask: **${task}**\n\nUse **Resume** or say **please continue** to continue from here.`;
    },

    removeInterruptedSessionMessages() {
      this.chatMessages = (this.chatMessages || []).filter(message => !message.interruptedSessionNotice);
    },

    injectInterruptedSessionMessage() {
      this.removeInterruptedSessionMessages();
      const session = this.interruptedSession;
      if (!session) return;
      if (session.status === 'approval_required') return;
      const content = this.interruptedSessionMessageContent(session);
      if (!content) return;
      this.chatMessages.push({
        id: `interrupted-${session.session_id}`,
        role: 'assistant',
        content,
        created_at: session.updated_at ? new Date(session.updated_at * 1000).toISOString() : new Date().toISOString(),
        mode: 'agent',
        threadMode: 'recover',
        error: session.status === 'interrupted',
        pendingApproval: session.status === 'approval_required' ? session.approval : null,
        interruptedSessionNotice: true,
        resources: [],
      });
      this.$nextTick(() => requestAnimationFrame(() => this.scrollChat(true)));
    },

    /* ── User message continuity actions ─────────────────────────────── */

    editUserMessage(msg) {
      // Put the message back into the composer for editing — do NOT re-send yet
      this.chatInput = msg.content;
      this.$nextTick(() => {
        const el = this.$refs.chatComposer;
        if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
        this.resetChatComposerHeight?.();
      });
      this.showToast('Message loaded for editing — modify and send when ready');
    },

    async retryUserMessage(msg) {
      // Re-send the user message exactly as-is (creates new assistant response)
      if (this.chatLoading) return;
      this.chatInput = msg.content;
      await this.$nextTick();
      this.sendChat();
    },

    isExplicitResumeText(text) {
      const lower = String(text || '').trim().toLowerCase();
      if (!lower) return false;
      if (['continue', 'please continue', 'go', 'go ahead', 'yes', 'yes continue', 'ok', 'ok continue'].includes(lower)) {
        return true;
      }
      return [
        'continue from',
        'continue the task',
        'continue working',
        'resume the task',
        'resume where',
        'pick up where',
        'keep going',
      ].some(phrase => lower.includes(phrase));
    },

    lastContinuableTask() {
      const messages = Array.isArray(this.chatMessages) ? [...this.chatMessages] : [];
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const item = messages[index] || {};
        if (item.interruptedSessionNotice) continue;
        if (item.role === 'assistant' && item.retryMsg) {
          const retryMsg = String(item.retryMsg || '').trim();
          if (retryMsg && !this.isExplicitResumeText(retryMsg)) {
            return {
              task: retryMsg,
              source: 'last_error',
              resourceIds: Array.isArray(item.retryResources) ? item.retryResources : [],
            };
          }
        }
        if (item.role === 'user') {
          const content = String(item.content || '').trim();
          if (!content || this.isExplicitResumeText(content)) continue;
          return {
            task: content,
            source: 'last_user',
            resourceIds: (item.resources || []).map(resource => Number(resource?.id || resource)).filter(Boolean),
          };
        }
      }
      return null;
    },

    resumePayload(message, source = 'resume') {
      const session = this.interruptedSession;
      if (!this.isExplicitResumeText(message) && !['retry_button', 'resume_banner', 'approval_continue'].includes(source)) {
        return {};
      }
      if (session && session.session_id) {
        return {
          resume_session_id: session.session_id,
          resume_reason: source,
        };
      }
      const fallback = this.lastContinuableTask();
      if (!fallback?.task) return {};
      return {
        continue_task: fallback.task,
        resume_reason: `${source}:${fallback.source}`,
      };
    },

    async quickResume() {
      // Inject "please continue" as a user message to resume the last agent session
      if (this.chatLoading) return;
      const autoSession = this.preferredResumeAutoSession('please continue', 'quick_resume');
      if (autoSession?.session_id) {
        if (String(this.chatProjectId || '') !== String(autoSession.workspace_id || '')) {
          this.activateWorkspaceTab?.(autoSession.workspace_id || '');
        }
        if (this.currentBackendSupportsAgent()) this.setConversationModeAuto({ persist: false });
        this.resumeBannerDismissed = true;
        await this.continueAutoSession(autoSession.session_id, { message: 'please continue' });
        return;
      }
      const resumePayload = this.resumePayload('please continue', 'resume_banner');
      this.removeInterruptedSessionMessages();
      this.resumeBannerDismissed = true;
      await this.sendChatSilent('please continue', 'agent', resumePayload);
    },

    /* ── Console Auto sessions ─────────────────────────────────────── */

    autoSessionRuntimePayload() {
      if (typeof this.currentSandboxRuntimePayload === 'function') {
        return this.currentSandboxRuntimePayload();
      }
      const backend = String(this.settingsForm?.ai_backend || this.runtimeStatus?.backend || 'api').toLowerCase();
      const payload = { backend };
      if (backend === 'api') {
        payload.api_provider = this.settingsForm?.api_provider
          || this.runtimeStatus?.selected_api_provider?.provider_id
          || 'deepseek';
        payload.api_model = this.selectedApiProviderModel?.()
          || this.runtimeStatus?.selected_api_provider?.api_model
          || '';
      } else if (backend === 'cli') {
        payload.cli_path = this.settingsForm?.cli_runtime_path || this.runtimeStatus?.cli_binary || '';
        payload.cli_model = this.settingsForm?.cli_runtime_model || this.runtimeStatus?.cli_model || '';
        payload.cli_session_persistence_enabled = !!this.settingsForm?.claude_cli_session_persistence_enabled;
      } else if (backend === 'ollama') {
        payload.ollama_model = this.activeChatModel?.() || this.settingsForm?.ollama_model || this.runtimeStatus?.active_model || '';
      }
      return payload;
    },

    sortAutoSessions(rows = []) {
      return [...(rows || [])]
        .map(item => ({ ...item, changed_files_count: Number(item?.changed_files_count || 0) }))
        .sort((a, b) => String(b?.updated_at || b?.created_at || '').localeCompare(String(a?.updated_at || a?.created_at || '')));
    },

    currentWorkspaceAutoSession() {
      const workspaceId = String(this.chatProjectId || '').trim();
      if (!workspaceId) return null;
      const rows = this.sortAutoSessions((this.autoSessions || []).filter(item => String(item?.workspace_id || '') === workspaceId));
      return rows.find(item => !['applied', 'discarded'].includes(String(item?.status || ''))) || rows[0] || null;
    },

    autoSessionCanDriveMode(session = null) {
      const status = String(session?.status || '').trim().toLowerCase();
      return ['ready', 'running', 'approval_required', 'review_ready'].includes(status);
    },

    activeAutoSession() {
      const current = this.currentWorkspaceAutoSession();
      if (this.autoSessionCanDriveMode(current)) return current;
      return this.sortAutoSessions(this.autoSessions).find(item => this.autoSessionCanDriveMode(item)) || null;
    },

    maybeStartAutoWorkspacePreview(session = null) {
      const current = session || this.currentWorkspaceAutoSession();
      if (!current || !this.autonomousConsoleActive?.() || this.isMobile) return;
      const workspaceId = String(this.chatProjectId || '').trim();
      if (!workspaceId || String(current.workspace_id || '') !== workspaceId) return;
      if (this.currentWorkspacePreview?.()?.url || this.workspacePreview?.loading) return;
      const status = String(current.status || '');
      if (!['running', 'review_ready', 'approval_required'].includes(status)) return;
      const key = `${workspaceId}:${current.session_id}`;
      if (!this._autoPreviewAutostarted) this._autoPreviewAutostarted = {};
      if (this._autoPreviewAutostarted[key]) return;
      this._autoPreviewAutostarted[key] = true;
      queueMicrotask(() => this.ensureWorkspacePreview?.({ openExternal: false, attachBrowser: false, silent: true }));
    },

    autoSessionThreadMode(session) {
      const status = String(session?.status || '');
      if (status === 'approval_required' || status === 'error') return 'recover';
      return 'auto';
    },

    autoSessionLiveFeed(session) {
      if (!session) return [];
      const workspaceId = String(session.workspace_id || '').trim();
      const sessionId = String(session.session_id || '').trim();
      const liveWorkspaceId = String(this.liveOperator?.workspaceId || '').trim();
      const liveSessionId = String(this.liveOperator?.autoSessionId || '').trim();
      if (!workspaceId || workspaceId !== liveWorkspaceId) return [];
      if (liveSessionId && sessionId && liveSessionId !== sessionId) return [];
      return Array.isArray(this.liveOperatorFeed) ? this.liveOperatorFeed.slice(-3) : [];
    },

    autoSessionMessageContent(session) {
      if (!session) return '';
      const title = session.title || 'Auto session';
      const status = String(session.status || 'ready');
      const summary = String(session.detail || session.last_error || '').trim();
      const changed = Number(session.changed_files_count || 0);
      const workspace = session.workspace_name || this.liveOperatorWorkspaceName() || 'this workspace';
      const liveFeed = this.autoSessionLiveFeed(session);
      const phaseLabel = (phase = '') => {
        const key = String(phase || '').trim().toLowerCase();
        if (['execute', 'executing', 'working'].includes(key)) return 'Working';
        if (['verify', 'verifying', 'review'].includes(key)) return 'Checking';
        if (['plan', 'planning'].includes(key)) return 'Planning';
        if (['recover', 'retrying'].includes(key)) return 'Recovering';
        if (key === 'blocked') return 'Blocked';
        return 'Latest';
      };
      const liveLines = liveFeed
        .map(entry => {
          const titleText = String(entry?.title || '').trim();
          const detailText = String(entry?.detail || '').trim();
          const lead = titleText || detailText;
          const tail = titleText && detailText ? detailText : '';
          return lead ? `- ${phaseLabel(entry?.phase)}: ${lead}${tail ? ` — ${tail}` : ''}` : '';
        })
        .filter(Boolean)
        .join('\n');
      if (status === 'running') {
        return `🔄 I’m working on **${title}** in the sandbox for **${workspace}**.${liveLines ? `\n\n**Latest**\n${liveLines}` : '\n\nI’ll keep going until I either need your approval or have something ready for review.'}`;
      }
      if (status === 'approval_required') {
        return `⚠️ I’m paused on **${title}** because I need approval to continue.\n\n${summary || 'Approve the step and I’ll carry on from the same place.'}`;
      }
      if (status === 'review_ready') {
        return `✅ I’ve finished **${title}** and it’s ready for review.\n\nChanged files: **${changed}**.\nUse **Report**, **Apply**, or **Discard** in the Auto panel.`;
      }
      if (status === 'applied') {
        return `✅ I applied **${title}** back to the source workspace.`;
      }
      if (status === 'discarded') {
        return `🗑 I discarded **${title}**.`;
      }
      if (status === 'error') {
        return `⚠️ I hit a problem while working on **${title}**.\n\n${summary || 'I didn’t get to a clean reviewable handoff yet.'}`;
      }
      return `🤖 **${title}** is ready for the next Auto step.`;
    },

    syncAutoSessionNoticeForCurrentWorkspace() {
      const workspaceId = String(this.chatProjectId || '').trim();
      const current = this.currentWorkspaceAutoSession();
      this.chatMessages = (this.chatMessages || []).filter(message => {
        if (!message?.autoSessionNotice) return true;
        const messageWorkspace = String(message.autoSessionWorkspaceId || '').trim();
        return workspaceId && messageWorkspace && messageWorkspace !== workspaceId;
      });
      if (!current || !workspaceId) return;
      const id = `auto-session-${current.session_id}`;
      const nextMessage = {
        id,
        role: 'assistant',
        content: this.autoSessionMessageContent(current),
        created_at: current.updated_at || current.created_at || new Date().toISOString(),
        mode: 'agent',
        threadMode: this.autoSessionThreadMode(current),
        autoSessionNotice: true,
        autoSessionWorkspaceId: workspaceId,
        autoSessionId: current.session_id,
        resources: [],
      };
      const idx = (this.chatMessages || []).findIndex(message => message.id === id);
      if (idx >= 0) this.chatMessages[idx] = { ...this.chatMessages[idx], ...nextMessage };
      else this.chatMessages.push(nextMessage);
      this.$nextTick(() => requestAnimationFrame(() => this.scrollChat(true)));
    },

    updateAutoSessionRecord(session) {
      if (!session?.session_id) return;
      const rows = Array.isArray(this.autoSessions) ? [...this.autoSessions] : [];
      const idx = rows.findIndex(item => String(item?.session_id || '') === String(session.session_id));
      if (idx >= 0) rows[idx] = { ...rows[idx], ...session };
      else rows.push({ ...session });
      this.autoSessions = this.sortAutoSessions(rows);
      if (this.autoSessionReview?.open && String(this.autoSessionReview?.session?.session_id || '') === String(session.session_id)) {
        this.autoSessionReview.session = { ...this.autoSessionReview.session, ...session };
      }
      this.syncAutoSessionNoticeForCurrentWorkspace();
      if (String(this.chatProjectId || '') === String(session.workspace_id || '')) {
        this.loadWorkspacePreview?.();
        this.maybeStartAutoWorkspacePreview?.(session);
      }
    },

    syncAutoSessionsFromSnapshot(rows = []) {
      const byId = new Map((this.autoSessions || []).map(item => [String(item?.session_id || ''), item]));
      for (const row of rows || []) {
        const key = String(row?.session_id || '');
        if (!key) continue;
        byId.set(key, { ...(byId.get(key) || {}), ...row });
      }
      this.autoSessions = this.sortAutoSessions([...byId.values()]);
      this.syncAutoSessionNoticeForCurrentWorkspace();
    },

    async loadAutoSessions() {
      try {
        const data = await this.api('GET', '/api/auto/sessions');
        this.autoSessions = this.sortAutoSessions(data?.sessions || []);
      } catch (_) {
        this.autoSessions = [];
      }
      let restoreAutoIntent = '';
      try {
        restoreAutoIntent = String(
          typeof this.readWindowPref === 'function'
            ? this.readWindowPref('consoleAutoIntent', localStorage.getItem('axon.consoleAutoIntent') || '')
            : (localStorage.getItem('axon.consoleAutoIntent') || '')
        ).trim().toLowerCase();
      } catch (_) {}
      if (this.currentBackendSupportsAgent() && restoreAutoIntent === 'true' && this.activeAutoSession()) {
        this.setConversationModeAuto({ persist: false });
      }
      this.syncAutoSessionNoticeForCurrentWorkspace();
      this.loadWorkspacePreview?.();
      this.maybeStartAutoWorkspacePreview?.();
      return this.autoSessions;
    },

    async viewAutoSessionReport(sessionId) {
      const id = String(sessionId || '').trim();
      if (!id) return;
      try {
        const data = await this.api('GET', `/api/auto/${encodeURIComponent(id)}`);
        if (data?.session) this.updateAutoSessionRecord(data.session);
        this.autoSessionReview = { open: true, session: data?.session || null };
      } catch (e) {
        this.showToast(e.message || 'Auto session report not ready yet');
      }
    },

    closeAutoSessionReport() {
      this.autoSessionReview = { open: false, session: null };
    },

    async refreshAutoSession(sessionId) {
      const id = String(sessionId || '').trim();
      if (!id) return;
      try {
        const data = await this.api('GET', `/api/auto/${encodeURIComponent(id)}`);
        if (data?.session) this.updateAutoSessionRecord(data.session);
        if (this.autoSessionReview?.open && String(this.autoSessionReview?.session?.session_id || '') === id) {
          this.autoSessionReview = { open: true, session: data?.session || null };
        }
      } catch (e) {
        this.showToast(e.message || 'Auto session not ready yet');
      }
    },

    async startAutoSessionFromChat(message, resourceIds = [], composerOptions = {}) {
      if (!this.chatProjectId) {
        throw new Error('Select a workspace before starting Auto mode.');
      }
      if (this.currentBackendSupportsAgent()) this.setConversationModeAuto({ persist: false });
      const payload = {
        message,
        project_id: parseInt(this.chatProjectId, 10),
        resource_ids: resourceIds,
        composer_options: { ...(composerOptions || {}), agent_role: 'auto' },
        ...this.autoSessionRuntimePayload(),
      };
      const data = await this.api('POST', '/api/auto/start', payload);
      if (data?.session) this.updateAutoSessionRecord(data.session);
      this.loadWorkspacePreview?.();
      if (data?.requires_resolution) {
        this.showToast('Finish the current Auto session first — continue, apply, or discard it.');
      } else if (data?.already_running) {
        this.showToast('Auto session already running');
      } else if (data?.started) {
        this.showToast('Auto session started');
      }
      return data;
    },

    async continueAutoSession(sessionId = '', options = {}) {
      const target = String(sessionId || this.currentWorkspaceAutoSession()?.session_id || '').trim();
      if (!target) {
        this.showToast('No Auto session to continue in this workspace');
        return null;
      }
      if (this.currentBackendSupportsAgent()) this.setConversationModeAuto({ persist: false });
      const payload = {
        message: String(options?.message || 'please continue'),
        project_id: parseInt(String(this.chatProjectId || this.currentWorkspaceAutoSession()?.workspace_id || 0), 10) || null,
        composer_options: { ...(this.normalizedComposerOptions?.() || {}), agent_role: 'auto' },
        ...this.autoSessionRuntimePayload(),
      };
      const data = await this.api('POST', `/api/auto/${encodeURIComponent(target)}/continue`, payload);
      if (data?.session) this.updateAutoSessionRecord(data.session);
      this.loadWorkspacePreview?.();
      if (data?.already_running) this.showToast('Auto session already running');
      else if (data?.started) this.showToast('Auto session resumed');
      return data;
    },

    async applyAutoSession(sessionId = '') {
      const target = String(sessionId || this.currentWorkspaceAutoSession()?.session_id || '').trim();
      if (!target) return;
      if (!confirm('Apply this Auto session back to the source workspace?')) return;
      try {
        const data = await this.api('POST', `/api/auto/${encodeURIComponent(target)}/apply`);
        if (data?.session) this.updateAutoSessionRecord(data.session);
        this.loadWorkspacePreview?.();
        this.showToast(data?.summary || 'Auto session applied');
      } catch (e) {
        this.showToast(e.message || 'Failed to apply Auto session');
      }
    },

    async discardAutoSession(sessionId = '') {
      const target = String(sessionId || this.currentWorkspaceAutoSession()?.session_id || '').trim();
      if (!target) return;
      if (!confirm('Discard this Auto session and remove the sandbox worktree?')) return;
      try {
        await this.api('DELETE', `/api/auto/${encodeURIComponent(target)}`);
        this.autoSessions = this.sortAutoSessions((this.autoSessions || []).filter(item => String(item?.session_id || '') !== target));
        this.loadWorkspacePreview?.();
        if (this.autoSessionReview?.open && String(this.autoSessionReview?.session?.session_id || '') === target) {
          this.closeAutoSessionReport();
        }
        this.syncAutoSessionNoticeForCurrentWorkspace();
        this.showToast('Auto session discarded');
      } catch (e) {
        this.showToast(e.message || 'Failed to discard Auto session');
      }
    },

    /* ── Tasks ─────────────────────────────────────────────────────────── */

    async loadWorkspaceTasks() {
      try {
        const pid = this.chatProjectId ? `?project_id=${this.chatProjectId}&status=open` : '?status=open';
        const data = await this.api('GET', `/api/tasks${pid}`);
        this.workspaceTasks = data.tasks || data || [];
      } catch(e) { this.workspaceTasks = []; }
    },

    async toggleTaskDone(task) {
      const newStatus = task.status === 'done' ? 'open' : 'done';
      try {
        await this.api('PATCH', `/api/tasks/${task.id}`, { status: newStatus });
        task.status = newStatus;
      } catch(e) {}
    },

    async submitAddFolder() {
      const path = (this.addFolderModal.path || '').trim();
      if (!path) { this.addFolderModal.error = 'Please enter a folder path.'; return; }
      this.addFolderModal.loading = true;
      this.addFolderModal.error = '';
      try {
        const result = await this.api('POST', '/api/workspaces/add-folder', { path, persist_root: true });
        await this.loadProjects();
        const pid = result.project?.id;
        if (pid) { this.chatProjectId = String(pid); this.updateChatProject(); }
        this.addFolderModal.open = false;
        this.addFolderModal.path = '';
        this.showToast(`✓ Workspace "${result.project?.name || path}" added`);
      } catch(e) {
        this.addFolderModal.error = e.message || 'Failed to add folder.';
      }
      this.addFolderModal.loading = false;
    },

    async submitNewTask() {
      const title = (this.newTaskTitle || '').trim();
      if (!title) return;
      try {
        const pid = this.chatProjectId ? parseInt(this.chatProjectId) : null;
        const task = await this.api('POST', '/api/tasks', { title, project_id: pid });
        this.workspaceTasks.push(task);
        this.newTaskTitle = '';
        this.addingTask = false;
      } catch(e) {}
    },

    // ── Detect mission creation in AI response and trigger notification ──
    _checkMissionNotification(content) {
      if (!content) return;
      // Match the mission creation confirmation pattern from server
      const match = content.match(/✅\s*\*?\*?(\d+)\s*mission/i);
      if (match) {
        const count = parseInt(match[1], 10) || 1;
        // Extract mission titles from bold text patterns
        const titleMatches = [...content.matchAll(/[🔴🟠🔵⚪]\s*\*?\*?([^*\n]+?)\*?\*?\s*\(/g)];
        const titles = titleMatches.map(m => m[1].trim()).filter(Boolean);
        if (typeof this.notifyMissionsCreated === 'function') {
          this.notifyMissionsCreated(count, titles);
        }
        // Refresh the tasks list so Missions tab is up to date
        if (typeof this.loadTasks === 'function') {
          this.loadTasks();
        }
      }
    },

    // ── Detect playbook creation in AI response and trigger notification ──
    _checkPlaybookNotification(content) {
      if (!content) return;
      const match = content.match(/📋\s*\*?\*?(\d+)\s*playbook/i);
      if (match) {
        const count = parseInt(match[1], 10) || 1;
        const titleMatches = [...content.matchAll(/📝\s*\*?\*?([^*\n]+?)\*?\*?\s*$/gm)];
        const titles = titleMatches.map(m => m[1].trim()).filter(Boolean);
        if (typeof this.showStickyNotification === 'function') {
          this.showStickyNotification({
            type: 'success',
            title: `${count} Playbook${count > 1 ? 's' : ''} Saved`,
            body: titles.length ? titles.join(', ') : 'New playbooks created from chat',
            icon: '📋',
            duration: 8000,
            action: { label: 'View Playbooks', tab: 'prompts' },
          });
        }
        // Refresh prompts list
        if (typeof this.loadPrompts === 'function') {
          this.loadPrompts();
        }
      }
    },

    /* ── Silent auto-continue — no visible user bubble ── */
    async sendChatSilent(message, forceMode, extraPayload = {}) {
      const msg = (message || '').trim();
      if (!msg) return;
      const started = Date.now();
      while (this.chatLoading && (Date.now() - started) < 5000) {
        await new Promise(resolve => setTimeout(resolve, 120));
      }
      if (this.chatLoading) {
        this.showToast('Axon is still finishing the previous step. Try continue again in a moment.');
        return;
      }
      const mode = forceMode || this.effectiveChatMode(msg);
      const explicitResumeTarget = this.hasExplicitResumeTarget(extraPayload);
      const autoResumeSession = mode === 'agent'
        && !explicitResumeTarget
        ? this.preferredResumeAutoSession(msg, extraPayload?.resume_reason || 'resume')
        : null;
      if (autoResumeSession?.session_id && this.currentBackendSupportsAgent()) {
        this.setConversationModeAuto({ persist: false });
      }
      this.chatLoading = true;
      this.beginLiveOperator(mode, msg);
      if (autoResumeSession?.session_id) {
        try {
          if (String(this.chatProjectId || '') !== String(autoResumeSession.workspace_id || '')) {
            this.activateWorkspaceTab?.(autoResumeSession.workspace_id || '');
          }
          await this.continueAutoSession(autoResumeSession.session_id, { message: msg });
        } catch (e) {
          this.chatMessages.push({
            id: Date.now() + 1,
            role: 'assistant',
            content: `⚠️ Auto mode error: ${e.message}`,
            created_at: new Date().toISOString(),
            mode: 'agent',
            threadMode: 'recover',
            error: true,
            retryMsg: msg,
            resources: [],
          });
        }
        this.chatLoading = false;
        this.scrollChat();
        this._processQueue();
        return;
      }
      if (mode === 'agent' && this.autonomousConsoleActive()) {
        try {
          const currentAuto = this.currentWorkspaceAutoSession();
          if (this.isExplicitResumeText(msg) && currentAuto?.session_id) {
            await this.continueAutoSession(currentAuto.session_id, { message: msg });
          } else {
            await this.startAutoSessionFromChat(msg, [], this.normalizedComposerOptions());
          }
        } catch (e) {
          this.chatMessages.push({
            id: Date.now() + 1,
            role: 'assistant',
            content: `⚠️ Auto mode error: ${e.message}`,
            created_at: new Date().toISOString(),
            mode: 'agent',
            threadMode: 'recover',
            error: true,
            retryMsg: msg,
            resources: [],
          });
        }
        this.chatLoading = false;
        this.scrollChat();
        this._processQueue();
        return;
      }
      const respId = Date.now() + 1;
      this.chatMessages.push(this.createAssistantPlaceholder(respId, mode, []));
      this.scrollChat();
      try {
        await this.streamChatMessage(msg, mode, respId, [], extraPayload);
      } catch(e) {
        if (e.name === 'AbortError') { this.chatLoading = false; return; }
        const idx = this.chatMessages.findIndex(m => m.id === respId);
        if (idx >= 0) {
          this.chatMessages[idx].content = `⚠️ ${e.message}`;
          this.chatMessages[idx].streaming = false;
          this.chatMessages[idx].error = true;
        }
      }
      this.chatLoading = false;
      this.scrollChat();
      this._processQueue();
    },

    /* ── Message queue — add to queue while agent is working ── */
    _messageQueue: [],

    enqueueMessage(msg) {
      const text = (msg || '').trim();
      if (!text) return;
      if (!Array.isArray(this._messageQueue)) this._messageQueue = [];
      this._messageQueue.push(text);
      this.showToast(`Queued: "${text.slice(0, 40)}${text.length > 40 ? '…' : ''}" (${this._messageQueue.length} in queue)`);
    },

    _processQueue() {
      if (!Array.isArray(this._messageQueue) || !this._messageQueue.length) return;
      if (this.chatLoading) return;
      const next = this._messageQueue.shift();
      if (next) {
        this.chatInput = next;
        this.$nextTick(() => this.sendChat());
      }
    },

    /* ── Steer — send guidance to running agent ── */
    async steerAgent(guidance) {
      const text = (guidance || '').trim();
      if (!text) return;
      try {
        await this.api('POST', '/api/agent/steer', { message: text });
        this.showToast(`Steered: "${text.slice(0, 50)}…"`);
      } catch(e) {
        // Fallback: steer not supported by backend, queue instead
        this.enqueueMessage(text);
      }
    },

    /* ── Terminal mirroring — echo agent shell commands to xterm ── */
    _mirrorShellToTerminal(cmd, cwd) {
      try {
        const term = this._xtermInst;
        if (!term) return;
        const prefix = cwd ? `\x1b[90m${cwd}$\x1b[0m ` : '\x1b[90m$\x1b[0m ';
        term.writeln('');
        term.writeln(prefix + '\x1b[1;36m' + (cmd || '') + '\x1b[0m');
      } catch(e) { /* terminal not ready — safe to ignore */ }
    },

    _mirrorShellResultToTerminal(result) {
      try {
        if (!result || result.startsWith('BLOCKED_CMD:')) return;
        const term = this._xtermInst;
        if (!term) return;
        const lines = result.split('\n').slice(0, 40);
        lines.forEach(l => term.writeln(l));
        if (result.split('\n').length > 40) term.writeln('\x1b[90m… (truncated)\x1b[0m');
      } catch(e) { /* terminal not ready — safe to ignore */ }
    },

    _detectDevServerUrl(result) {
      try {
        if (!result || this.devPreview.url) return;
        // Match common dev server URL patterns, exclude Axon's own port (7734)
        const matches = result.match(/https?:\/\/(?:localhost|127\.0\.0\.1):(\d{2,5})/g) || [];
        const url = matches.find(u => !u.includes(':7734'));
        if (url) {
          this.devPreview.url = url;
          this.devPreview.visible = true;
          this.panelBrowserOpen = true;
        }
      } catch(e) { /* safe to ignore */ }
    },

    async sendChat() {
      if (this.businessMode && !this.chatInput?.trim()) {
        this.chatInput = this.businessComposerPrompt(this.businessView || 'invoice');
      }
      if (this.businessMode) {
        this.agentMode = false;
      }
      const msg = this.chatInput.trim();
      if (!msg || this.chatLoading) return;
      const mode = this.effectiveChatMode(msg);
      const researchPack = this.currentResearchPack();
      const packResources = researchPack?.resources || [];
      const attachedResources = this.mergeUniqueResources([...packResources, ...this.selectedResources]);
      const attachedResourceIds = attachedResources.map(resource => Number(resource.id)).filter(Boolean);
      const resumePayload = this.resumePayload(msg, 'typed_continue');
      const explicitResumeTarget = this.hasExplicitResumeTarget(resumePayload);
      const clarification = this.clarificationQuestionFor(msg, mode);
      if (clarification) {
        this.chatInput = '';
        this.followUpSuggestions = [];
        if (!this.composerOptions.pin_context) {
          this.selectedResources = [];
        }
        this.showResourcePicker = false;
        this.showComposerMenu = false;
        this.resetChatComposerHeight();
        this.addLocalClarificationExchange(msg, clarification, mode, attachedResources);
        return;
      }
      const autoResumeSession = mode === 'agent'
        && !explicitResumeTarget
        ? this.preferredResumeAutoSession(msg, 'typed_continue')
        : null;
      if (autoResumeSession?.session_id && this.currentBackendSupportsAgent()) {
          this.setConversationModeAuto({ persist: false });
      }
      this.setAgentStage(mode === 'agent' ? 'observe' : 'observe');

      this.chatInput = '';
      this.followUpSuggestions = [];
      this._userScrolled = false; // resume auto-scroll for the new message
      if (!this.composerOptions.pin_context) {
        this.selectedResources = [];
      }
      this.showResourcePicker = false;
      this.showComposerMenu = false;
      this.resetChatComposerHeight();
      this.chatMessages.push({
        id: Date.now(),
        role: 'user',
        content: msg,
        created_at: new Date().toISOString(),
        mode,
        threadMode: autoResumeSession?.session_id ? 'auto' : this.currentThreadMode(mode),
        resources: attachedResources,
      });
      this.chatLoading = true;
      this.beginLiveOperator(mode, msg);
      this.scrollChat();

      if (autoResumeSession?.session_id) {
        try {
          if (String(this.chatProjectId || '') !== String(autoResumeSession.workspace_id || '')) {
            this.activateWorkspaceTab?.(autoResumeSession.workspace_id || '');
          }
          await this.continueAutoSession(autoResumeSession.session_id, { message: msg });
        } catch (e) {
          this.chatMessages.push({
            id: Date.now() + 1,
            role: 'assistant',
            content: `⚠️ Auto mode error: ${e.message}`,
            created_at: new Date().toISOString(),
            mode: 'agent',
            threadMode: 'recover',
            error: true,
            retryMsg: msg,
            retryResources: attachedResourceIds,
            resources: [],
          });
          this.setAgentStage('recover');
          this.updateLiveOperator(mode, { type: 'error', message: e.message });
          this.clearLiveOperator(4200);
        }
        this.chatLoading = false;
        this.scrollChat();
        this._processQueue();
        return;
      }

      if (mode === 'agent' && this.autonomousConsoleActive()) {
        try {
          const currentAuto = this.currentWorkspaceAutoSession();
          if (this.isExplicitResumeText(msg) && currentAuto?.session_id) {
            await this.continueAutoSession(currentAuto.session_id, { message: msg });
          } else {
            await this.startAutoSessionFromChat(msg, attachedResourceIds, this.normalizedComposerOptions());
          }
        } catch (e) {
          this.chatMessages.push({
            id: Date.now() + 1,
            role: 'assistant',
            content: `⚠️ Auto mode error: ${e.message}`,
            created_at: new Date().toISOString(),
            mode: 'agent',
            threadMode: 'recover',
            error: true,
            retryMsg: msg,
            retryResources: attachedResourceIds,
            resources: [],
          });
          this.setAgentStage('recover');
          this.updateLiveOperator(mode, { type: 'error', message: e.message });
          this.clearLiveOperator(4200);
        }
        this.chatLoading = false;
        this.scrollChat();
        this._processQueue();
        return;
      }

      const respId = Date.now() + 1;
      this.chatMessages.push(this.createAssistantPlaceholder(respId, mode, attachedResourceIds));
      this.scrollChat();
      try {
        await this.streamChatMessage(msg, mode, respId, attachedResourceIds, resumePayload);
      } catch(e) {
        if (e.name === 'AbortError') {
          // User clicked stop — not an error
          this.chatLoading = false;
          this.scrollChat();
          return;
        }
        const idx = this.chatMessages.findIndex(m => m.id === respId);
        if (idx >= 0) {
          const isFetch = e.message === 'Failed to fetch' || e.message.includes('NetworkError');
          const isAgentDisconnect = isFetch && mode === 'agent';
          this.chatMessages[idx].content = isAgentDisconnect
            ? '⚠️ Connection lost mid-task. The agent session was saved — say **"please continue"** or tap Resume below to pick up exactly where it stopped.'
            : `⚠️ ${mode === 'agent' ? 'Agent error: ' : ''}${isFetch ? 'Connection lost.' : e.message}`;
          this.chatMessages[idx].streaming = false;
          this.chatMessages[idx].error = true;
          this.chatMessages[idx].retryMsg = msg;
          this.chatMessages[idx].mode = mode;
          this.chatMessages[idx].agentDisconnect = isAgentDisconnect;
          if (isFetch) this.serverConnected = false;
          this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
          // Refresh interrupted session banner after disconnect
          if (isAgentDisconnect) setTimeout(() => this.checkInterruptedSession(), 1500);
        }
        if (mode === 'agent') this.setAgentStage('recover');
        this.updateLiveOperator(mode, { type: 'error', message: e.message === 'Failed to fetch' || e.message.includes('NetworkError') ? 'Connection lost.' : e.message });
        this.clearLiveOperator(4200);
      }

      this.chatLoading = false;
      this.scrollChat();
      this._processQueue();
    },

    async retryChat(errorMsg) {
      const msg = errorMsg.retryMsg;
      if (!msg) return;
      const mode = this.effectiveChatMode(msg, errorMsg.mode || this.resolveChatMode(msg));
      const researchPack = this.currentResearchPack();
      const resourceIds = (errorMsg.retryResources && errorMsg.retryResources.length)
        ? errorMsg.retryResources
        : (researchPack?.resources || []).map(resource => Number(resource.id)).filter(Boolean);
      const resumePayload = mode === 'agent'
        ? this.resumePayload(msg, 'retry_button')
        : {};
      const explicitResumeTarget = this.hasExplicitResumeTarget(resumePayload);
      this.chatMessages = this.chatMessages.filter(m => m.id !== errorMsg.id);
      const autoResumeSession = mode === 'agent'
        && !explicitResumeTarget
        ? this.preferredResumeAutoSession(msg, 'retry_button')
        : null;
      if (autoResumeSession?.session_id && this.currentBackendSupportsAgent()) {
        this.setConversationModeAuto({ persist: false });
      }
      this.chatLoading = true;
      this.beginLiveOperator(mode, msg);
      this.scrollChat();
      if (autoResumeSession?.session_id) {
        try {
          if (String(this.chatProjectId || '') !== String(autoResumeSession.workspace_id || '')) {
            this.activateWorkspaceTab?.(autoResumeSession.workspace_id || '');
          }
          await this.continueAutoSession(autoResumeSession.session_id, { message: msg });
        } catch (e) {
          this.chatMessages.push({
            id: Date.now() + 1,
            role: 'assistant',
            content: `⚠️ Auto mode error: ${e.message}`,
            created_at: new Date().toISOString(),
            mode: 'agent',
            threadMode: 'recover',
            error: true,
            retryMsg: msg,
            retryResources: resourceIds,
            resources: [],
          });
          this.setAgentStage('recover');
          this.updateLiveOperator(mode, { type: 'error', message: e.message });
          this.clearLiveOperator(4200);
        }
        this.chatLoading = false;
        this.scrollChat();
        return;
      }
      if (mode === 'agent' && this.autonomousConsoleActive()) {
        try {
          const currentAuto = this.currentWorkspaceAutoSession();
          if (this.isExplicitResumeText(msg) && currentAuto?.session_id) {
            await this.continueAutoSession(currentAuto.session_id, { message: msg });
          } else {
            await this.startAutoSessionFromChat(msg, resourceIds, this.normalizedComposerOptions());
          }
        } catch (e) {
          this.chatMessages.push({
            id: Date.now() + 1,
            role: 'assistant',
            content: `⚠️ Auto mode error: ${e.message}`,
            created_at: new Date().toISOString(),
            mode: 'agent',
            threadMode: 'recover',
            error: true,
            retryMsg: msg,
            retryResources: resourceIds,
            resources: [],
          });
          this.setAgentStage('recover');
          this.updateLiveOperator(mode, { type: 'error', message: e.message });
          this.clearLiveOperator(4200);
        }
        this.chatLoading = false;
        this.scrollChat();
        return;
      }
      const respId = Date.now() + 1;
      this.chatMessages.push(this.createAssistantPlaceholder(respId, mode, resourceIds));
      try {
        await this.streamChatMessage(msg, mode, respId, resourceIds, resumePayload);
      } catch(e) {
        if (e.name === 'AbortError') {
          this.chatLoading = false;
          this.scrollChat();
          return;
        }
        const idx = this.chatMessages.findIndex(m => m.id === respId);
        const isFetch = e.message === 'Failed to fetch' || e.message.includes('NetworkError');
        if (isFetch) this.serverConnected = false;
        if (idx >= 0) {
          this.chatMessages[idx].content = isFetch
            ? '⚠️ Connection lost — check your network.'
            : `⚠️ ${mode === 'agent' ? 'Agent error: ' : 'Error: '}${e.message}`;
          this.chatMessages[idx].streaming = false;
          this.chatMessages[idx].error = true;
          this.chatMessages[idx].retryMsg = msg;
          this.chatMessages[idx].mode = mode;
          this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
        }
        if (mode === 'agent') this.setAgentStage('recover');
        this.updateLiveOperator(mode, { type: 'error', message: isFetch ? 'Connection lost.' : e.message });
        this.clearLiveOperator(4200);
      }
      this.chatLoading = false;
      this.scrollChat();
    },

    /* ── Canvas ───────────────────────────────────────────────── */

    openCanvas(message) {
      if (!message) return;
      const baseTitle = message.role === 'user' ? 'Your note' : 'Axon response';
      const derivedTitle = this.documentTitleFromMarkdown(message.content) || baseTitle;
      const runtimeBits = [
        message.mode === 'agent' ? '#NEXT-GEN' : 'Console',
        message.modelLabel || this.assistantRuntimeLabel() || '',
        message.created_at ? `Updated ${this.formatTime(message.created_at)}` : '',
      ].filter(Boolean);
      this.canvasModal = {
        open: true,
        title: derivedTitle,
        content: message.content || '',
        meta: runtimeBits.join(' · '),
        messageId: message.id || null,
      };
      document.body.classList.add('overflow-hidden');
    },

    /* ── Rendering helpers ────────────────────────────────────── */

    // renderMd is provided by helpers.js mixin (with code block renderer)

    formatTime(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      const now = new Date();
      const diff = now - d;
      if (diff < 60000) return 'just now';
      if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
      return d.toLocaleDateString();
    },

  };
}

window.axonChatMixin = axonChatMixin;
