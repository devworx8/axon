/* ══════════════════════════════════════════════════════════════
   Axon — Chat Workspace Modes
   ══════════════════════════════════════════════════════════════ */

function axonChatWorkspaceModesMixin() {
  const VALID_CONVERSATION_MODES = new Set(['ask', 'auto', 'agent', 'code', 'research', 'business']);
  const AUTO_RESTORABLE_STATUSES = new Set(['ready', 'running', 'approval_required', 'review_ready']);
  const AUTO_CONTINUABLE_STATUSES = new Set(['ready', 'running', 'approval_required', 'review_ready', 'error']);
  const AUTO_CLEARABLE_STATUSES = new Set(['ready', 'running', 'approval_required', 'review_ready', 'error']);

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

    currentRuntimeBackend() {
      const backend = this.settingsForm?.ai_backend || this.runtimeStatus?.backend || '';
      return String(backend || '').trim().toLowerCase() || 'api';
    },

    currentBackendSupportsAgent() {
      const backend = this.currentRuntimeBackend();
      return backend === 'ollama' || backend === 'cli';
    },

    usesOllamaBackend() {
      const backend = this.currentRuntimeBackend();
      return backend === 'ollama' || backend === 'cli';
    },

    activeChatModel() {
      const backend = this.currentRuntimeBackend();
      if (backend === 'cli') {
        return String(
          this.settingsForm?.cli_runtime_model
          || this.runtimeStatus?.cli_model
          || this.runtimeStatus?.active_model
          || ''
        ).trim();
      }
      if (backend === 'api') {
        return String(this.selectedApiProviderModel?.() || this.runtimeStatus?.active_model || '').trim();
      }
      return String(
        this.selectedChatModel
        || this.settingsForm?.code_model
        || this.settingsForm?.ollama_model
        || ''
      ).trim();
    },

    assistantRuntimeLabel() {
      const backend = this.currentRuntimeBackend();
      if (backend === 'cli') {
        return this.activeChatModel() || 'CLI Agent';
      }
      if (backend === 'ollama') {
        return this.activeChatModel() || 'Local model';
      }
      if (backend === 'api') {
        const provider = this.selectedApiProviderLabel?.() || '';
        const model = this.selectedApiProviderModel?.() || '';
        return model ? `${provider} · ${model}` : provider || 'Cloud';
      }
      return this.activeChatModel() || 'Runtime';
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

    sortAutoSessions(rows = []) {
      return sortSessions(rows);
    },

    currentWorkspaceAutoSession() {
      return this.workspaceAutoSessionFor(this.chatProjectId || '');
    },

    autoSessionCanDriveMode(session = null) {
      return AUTO_RESTORABLE_STATUSES.has(String(session?.status || '').trim().toLowerCase());
    },

    activeAutoSession() {
      const current = this.currentWorkspaceAutoSession?.() || null;
      if (this.autoSessionCanDriveMode(current)) return current;
      return this.sortAutoSessions(this.autoSessions || []).find(item => this.autoSessionCanDriveMode(item)) || null;
    },

    preferredResumeAutoSession(message = '', source = 'resume') {
      const explicit = !!this.isExplicitResumeText?.(message)
        || ['retry_button', 'resume_banner', 'approval_continue', 'typed_continue', 'quick_resume'].includes(String(source || '').trim().toLowerCase());
      if (!explicit) return null;
      const workspaceId = String(this.chatProjectId || '').trim();
      if (workspaceId) return this.currentWorkspaceAutoSession?.() || null;
      return this.activeAutoSession?.() || null;
    },

    autoSessionForMessage(message = {}) {
      const sessionId = String(message?.autoSessionId || message?.auto_session_id || message?.session_id || '').trim();
      if (!sessionId) return null;
      return (this.autoSessions || []).find(item => String(item?.session_id || '') === sessionId) || null;
    },

    autoSessionCanContinue(session = null) {
      return AUTO_CONTINUABLE_STATUSES.has(String(session?.status || '').trim().toLowerCase());
    },

    autoSessionCanClear(session = null) {
      return AUTO_CLEARABLE_STATUSES.has(String(session?.status || '').trim().toLowerCase());
    },

    autoSessionDiscardLabel(session = null) {
      const status = String(session?.status || '').trim().toLowerCase();
      if (['error', 'running', 'approval_required', 'ready'].includes(status)) return 'Clear stale run';
      return 'Discard run';
    },

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
      if (this.currentRuntimeBackend?.() === 'ollama' && (this.ollamaModels || []).length === 0) {
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
        const canRestoreAuto = !saved?.legacy || this.workspaceCanRestoreAutoMode(workspaceId);
        if (this.currentBackendSupportsAgent?.() && canRestoreAuto) {
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

    chatQuickActions() {
      const actions = [];
      const workspaceId = String(this.chatProjectId || '').trim();
      const currentAuto = this.currentWorkspaceAutoSession?.() || null;
      const currentInterrupted = this.interruptedSession || null;
      const currentWorkspaceName = String(
        this.chatProject?.name
        || this.workspaceTabLabel?.(workspaceId)
        || ''
      ).trim();

      let resumeWorkspaceId = workspaceId;
      let resumeLabel = currentWorkspaceName;
      let resumeSessionId = String(currentAuto?.session_id || '').trim();

      if (!resumeWorkspaceId) {
        const candidate = this.chooseInitialWorkspaceRestoreCandidate?.({
          autoSessions: this.autoSessions || [],
          interruptedSession: currentInterrupted,
          savedProjectId: '',
        }) || null;
        resumeWorkspaceId = String(candidate?.workspaceId || '').trim();
        resumeLabel = String(candidate?.label || candidate?.workspaceLabel || '').trim();
        resumeSessionId = String(
          this.workspaceAutoSessionFor?.(resumeWorkspaceId)?.session_id
          || this.newestRestorableAutoSession?.(this.autoSessions || [])?.session_id
          || ''
        ).trim();
      }

      if (resumeWorkspaceId || currentInterrupted || currentAuto) {
        actions.push({
          id: 'resume-last-run',
          type: 'action',
          action: 'resume_active_workspace',
          label: resumeLabel ? `Resume ${resumeLabel}` : 'Resume last run',
          workspaceId: resumeWorkspaceId,
          sessionId: resumeSessionId,
        });
      }

      const clearable = currentAuto || (resumeSessionId ? this.workspaceAutoSessionFor?.(resumeWorkspaceId) : null);
      if (this.autoSessionCanClear?.(clearable)) {
        actions.push({
          id: 'clear-stale-run',
          type: 'action',
          action: 'clear_stale_resumable_session',
          label: this.autoSessionDiscardLabel?.(clearable) || 'Clear stale run',
          sessionId: String(clearable?.session_id || '').trim(),
          workspaceId: String(clearable?.workspace_id || resumeWorkspaceId || '').trim(),
        });
      }

      if (!workspaceId) return actions;

      actions.push({
        id: 'inspect-workspace',
        type: 'action',
        action: 'inspect_workspace',
        label: 'Inspect this workspace',
        prompt: `Inspect workspace ${currentWorkspaceName || workspaceId} and summarize the current state.`,
      });
      actions.push({
        id: 'scan-blockers',
        type: 'action',
        action: 'scan_repo_blockers',
        label: 'Scan repo and surface blockers',
        prompt: `Scan workspace ${currentWorkspaceName || workspaceId} and surface blockers, failing areas, and risky changes.`,
      });
      actions.push({
        id: 'workspace-preview',
        type: 'action',
        action: 'start_live_page',
        label: this.previewReadyForCurrentWorkspace?.() ? 'Open live page' : 'Start live page',
        workspaceId,
      });

      const approvalWorkspaceId = String(this.pendingAgentApproval?.workspaceId || '').trim();
      if (!approvalWorkspaceId || approvalWorkspaceId === workspaceId) {
        actions.push({
          id: 'check-approvals',
          type: 'action',
          action: 'check_approvals',
          label: 'Check approvals',
          prompt: 'Check pending approvals and tell me what is blocked.',
        });
      }

      return actions;
    },

    async runChatQuickAction(action = {}) {
      const nextAction = String(action?.action || '').trim();
      if (!nextAction) return null;
      if (nextAction === 'clear_stale_resumable_session') {
        return this.discardAutoSession?.(action.sessionId || '');
      }
      if (nextAction === 'resume_active_workspace') {
        const workspaceId = String(action?.workspaceId || '').trim();
        if (workspaceId && workspaceId !== String(this.chatProjectId || '').trim()) {
          this.activateWorkspaceTab?.(workspaceId);
          await this.$nextTick?.();
        }
        if (action?.sessionId) {
          return this.continueAutoSession?.(action.sessionId, {
            message: 'please continue',
            workspaceId,
          });
        }
        return this.quickResume?.();
      }
      if (nextAction === 'start_live_page') {
        return this.ensureWorkspacePreview?.({ openExternal: false, attachBrowser: false });
      }
      const prompt = String(action?.prompt || '').trim();
      if (!prompt) return null;
      return this.sendChatSilent?.(prompt, 'agent', {});
    },
  };
}

window.axonChatWorkspaceModesMixin = axonChatWorkspaceModesMixin;
