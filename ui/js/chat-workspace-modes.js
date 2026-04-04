/* ══════════════════════════════════════════════════════════════
   Axon — Chat Workspace Modes
   ══════════════════════════════════════════════════════════════ */

function axonChatWorkspaceModesMixin() {
  const VALID_CONVERSATION_MODES = new Set(['ask', 'auto', 'agent', 'code', 'research', 'business']);
  const AUTO_RESTORABLE_STATUSES = new Set(['ready', 'running', 'approval_required', 'review_ready']);

  const sortSessions = (rows = []) => [...(rows || [])]
    .map(item => ({ ...item, changed_files_count: Number(item?.changed_files_count || 0) }))
    .sort((a, b) => String(b?.updated_at || b?.created_at || '').localeCompare(String(a?.updated_at || a?.created_at || '')));

  return {
    workspaceConversationModeKey(workspaceId = null) {
      const raw = workspaceId == null ? this.chatProjectId : workspaceId;
      const value = String(raw || '').trim();
      return value || '__all__';
    },

    normalizeConversationMode(mode = '') {
      const value = String(mode || '').trim().toLowerCase();
      return VALID_CONVERSATION_MODES.has(value) ? value : 'ask';
    },

    readWorkspaceConversationModeMap() {
      try {
        const raw = String(this.readWindowPref?.('workspaceConversationModes', '{}') || '{}').trim();
        const parsed = JSON.parse(raw || '{}');
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch (_) {
        return {};
      }
    },

    writeWorkspaceConversationModeMap(map = {}) {
      try {
        this.writeWindowPref?.('workspaceConversationModes', JSON.stringify(map || {}));
      } catch (_) {}
    },

    legacyConversationModeState() {
      let autoIntent = '';
      let mode = '';
      try {
        autoIntent = String(
          typeof this.readWindowPref === 'function'
            ? this.readWindowPref('consoleAutoIntent', localStorage.getItem('axon.consoleAutoIntent') || '')
            : (localStorage.getItem('axon.consoleAutoIntent') || '')
        ).trim().toLowerCase();
      } catch (_) {}
      if (autoIntent === 'true') return { mode: 'auto', legacy: true };
      try {
        mode = String(
          typeof this.readWindowPref === 'function'
            ? this.readWindowPref('consoleMode', localStorage.getItem('axon.consoleMode') || '')
            : (localStorage.getItem('axon.consoleMode') || '')
        ).trim().toLowerCase();
      } catch (_) {}
      if (VALID_CONVERSATION_MODES.has(mode)) return { mode, legacy: true };
      return null;
    },

    savedWorkspaceConversationModeState(workspaceId = null) {
      const key = this.workspaceConversationModeKey(workspaceId);
      const map = this.readWorkspaceConversationModeMap();
      const row = map[key];
      if (row && typeof row === 'object') {
        return {
          mode: this.normalizeConversationMode(row.mode || ''),
          updatedAt: String(row.updatedAt || '').trim(),
          legacy: false,
        };
      }
      const legacy = this.legacyConversationModeState();
      return legacy ? { ...legacy, mode: this.normalizeConversationMode(legacy.mode || '') } : null;
    },

    clearLegacyConversationModePrefs() {
      try {
        this.writeWindowPref?.('consoleMode', '');
        this.writeWindowPref?.('consoleAutoIntent', '');
      } catch (_) {}
      try {
        localStorage.removeItem('axon.consoleMode');
        localStorage.removeItem('axon.consoleAutoIntent');
      } catch (_) {}
    },

    workspaceAutoSessionFor(workspaceId = null) {
      const key = String(workspaceId == null ? this.chatProjectId : workspaceId).trim();
      if (!key) return null;
      const rows = sortSessions((this.autoSessions || []).filter(item => String(item?.workspace_id || '') === key));
      return rows.find(item => !['applied', 'discarded'].includes(String(item?.status || ''))) || rows[0] || null;
    },

    workspaceCanRestoreAutoMode(workspaceId = null) {
      const session = this.workspaceAutoSessionFor(workspaceId);
      if (!session) return false;
      if (typeof this.autoSessionCanDriveMode === 'function') return !!this.autoSessionCanDriveMode(session);
      return AUTO_RESTORABLE_STATUSES.has(String(session?.status || '').trim().toLowerCase());
    },

    async fetchAutoSessionsSnapshot() {
      try {
        const data = await this.api('GET', '/api/auto/sessions');
        return this.sortAutoSessions ? this.sortAutoSessions(data?.sessions || []) : sortSessions(data?.sessions || []);
      } catch (_) {
        return [];
      }
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
      if (options.persist === true) this.persistConversationModePreference({ mode: 'ask' });
    },

    setConversationModeAuto(options = {}) {
      this.resetPrimaryConversationModes();
      this.agentMode = true;
      this.composerOptions.agent_role = 'auto';
      this.composerOptions.safe_mode = true;
      this.composerOptions.require_approval = false;
      this.composerOptions.external_mode = 'local_first';
      if (options.persist === true) this.persistConversationModePreference({ mode: 'auto' });
    },

    setConversationModeAgent(options = {}) {
      this.resetPrimaryConversationModes();
      this.agentMode = true;
      if (this.usesOllamaBackend?.() && (this.ollamaModels || []).length === 0) {
        this.loadOllamaModels?.();
      }
      if (options.persist === true) this.persistConversationModePreference({ mode: 'agent' });
    },

    setConversationModeCode(options = {}) {
      this.resetPrimaryConversationModes();
      this.composerOptions.intelligence_mode = 'analyze';
      this.composerOptions.action_mode = 'generate';
      if (options.persist === true) this.persistConversationModePreference({ mode: 'code' });
    },

    setConversationModeResearch(options = {}) {
      this.resetPrimaryConversationModes();
      this.composerOptions.intelligence_mode = 'deep_research';
      if (options.persist === true) this.persistConversationModePreference({ mode: 'research' });
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
      const key = this.normalizeConversationMode(mode);
      const opts = this.normalizedComposerOptions ? this.normalizedComposerOptions() : (this.composerOptions || {});
      if (key === 'business') return !!this.businessMode;
      if (key === 'auto') return !this.businessMode && !!this.agentMode && opts.agent_role === 'auto';
      if (key === 'agent') return !!this.agentMode && !this.businessMode && opts.agent_role !== 'auto';
      if (key === 'code') {
        return !this.businessMode && !this.agentMode
          && opts.intelligence_mode === 'analyze'
          && opts.action_mode === 'generate';
      }
      if (key === 'research') {
        return !this.businessMode && !this.agentMode
          && opts.intelligence_mode === 'deep_research';
      }
      return !this.businessMode
        && !this.agentMode
        && opts.intelligence_mode === 'ask'
        && !opts.action_mode
        && !opts.agent_role;
    },

    toggleAgentMode(force = null) {
      const enabled = typeof force === 'boolean' ? force : !this.agentMode;
      if (enabled) this.chooseConversationModeAgent();
      else this.chooseConversationModeAsk();
    },

    activePrimaryConversationMode() {
      if (this.businessMode) return 'business';
      const opts = this.normalizedComposerOptions ? this.normalizedComposerOptions() : (this.composerOptions || {});
      if (this.agentMode && opts.agent_role === 'auto') return 'auto';
      if (this.agentMode) return 'agent';
      if (opts.intelligence_mode === 'analyze' && opts.action_mode === 'generate') return 'code';
      if (opts.intelligence_mode === 'deep_research') return 'research';
      return 'ask';
    },

    autonomousConsoleActive() {
      const opts = this.normalizedComposerOptions ? this.normalizedComposerOptions() : (this.composerOptions || {});
      return !!this.agentMode && !this.businessMode && opts.agent_role === 'auto';
    },

    persistConversationModePreference(options = {}) {
      const workspaceId = options?.workspaceId ?? this.chatProjectId ?? '';
      const key = this.workspaceConversationModeKey(workspaceId);
      const mode = this.normalizeConversationMode(options?.mode || this.activePrimaryConversationMode());
      const map = this.readWorkspaceConversationModeMap();
      map[key] = {
        mode,
        updatedAt: new Date().toISOString(),
      };
      this.writeWorkspaceConversationModeMap(map);
      this.clearLegacyConversationModePrefs();
    },

    restoreConversationModePreference(options = {}) {
      const workspaceId = options?.workspaceId ?? this.chatProjectId ?? '';
      const saved = this.savedWorkspaceConversationModeState(workspaceId);
      const mode = this.normalizeConversationMode(saved?.mode || 'ask');
      if (mode === 'business') {
        this.toggleBusinessMode(true, { persist: false });
        return mode;
      }
      if (mode === 'agent') {
        if (this.currentBackendSupportsAgent?.()) this.setConversationModeAgent({ persist: false });
        else this.setConversationModeAsk({ persist: false });
        return this.activePrimaryConversationMode();
      }
      if (mode === 'auto') {
        if (this.currentBackendSupportsAgent?.()) {
          this.setConversationModeAuto({ persist: false });
          return mode;
        }
        this.setConversationModeAsk({ persist: false });
        return 'ask';
      }
      if (mode === 'code') {
        this.setConversationModeCode({ persist: false });
        return mode;
      }
      if (mode === 'research') {
        this.setConversationModeResearch({ persist: false });
        return mode;
      }
      this.setConversationModeAsk({ persist: false });
      return 'ask';
    },

    toggleBusinessMode(force = null, options = {}) {
      const enabled = typeof force === 'boolean' ? force : !this.businessMode;
      if (enabled) {
        this.resetPrimaryConversationModes();
        this.businessMode = true;
        this.composerOptions.intelligence_mode = 'build_brief';
        this.composerOptions.action_mode = 'generate';
      } else {
        this.setConversationModeAsk({ persist: false });
      }
      if (options.persist !== false) this.persistConversationModePreference({ mode: enabled ? 'business' : 'ask' });
    },

    async loadAutoSessions(options = {}) {
      const rows = Array.isArray(options?.rows)
        ? options.rows
        : await this.fetchAutoSessionsSnapshot();
      this.autoSessions = rows;
      if (options.restoreMode !== false) {
        this.restoreConversationModePreference({ workspaceId: this.chatProjectId || '' });
      }
      if (options.syncCurrentWorkspaceNotice !== false) this.syncAutoSessionNoticeForCurrentWorkspace?.();
      if (options.loadPreview !== false) this.loadWorkspacePreview?.();
      if (options.maybeStartPreview !== false) this.maybeStartAutoWorkspacePreview?.();
      return this.autoSessions;
    },
  };
}

window.axonChatWorkspaceModesMixin = axonChatWorkspaceModesMixin;
