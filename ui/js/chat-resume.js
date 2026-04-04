/* ══════════════════════════════════════════════════════════════
   Axon — Chat Resume Module
   ══════════════════════════════════════════════════════════════ */

function axonResolveResumeWorkspaceId(interruptedSession = null, autoSession = null, currentWorkspaceId = '') {
  const interruptedWorkspaceId = String(
    interruptedSession?.workspace_id
    || interruptedSession?.workspaceId
    || ''
  ).trim();
  if (interruptedWorkspaceId) return interruptedWorkspaceId;

  const autoWorkspaceId = String(
    autoSession?.workspace_id
    || autoSession?.workspaceId
    || ''
  ).trim();
  if (autoWorkspaceId) return autoWorkspaceId;

  return String(currentWorkspaceId || '').trim();
}

function axonResumeActionLabel(workspaceLabel = '') {
  const label = String(workspaceLabel || '').trim();
  return label ? `Continue in ${label}` : 'Continue';
}

function axonChatResumeMixin() {
  return {
    resumeTimestamp(value = null) {
      if (value == null || value === '') return 0;
      if (typeof value === 'number' && Number.isFinite(value)) {
        return value > 1e12 ? value : value * 1000;
      }
      const numeric = Number(value);
      if (Number.isFinite(numeric) && String(value).trim() !== '') {
        return numeric > 1e12 ? numeric : numeric * 1000;
      }
      const parsed = Date.parse(String(value || '').trim());
      return Number.isFinite(parsed) ? parsed : 0;
    },

    isExplicitResumeText(text = '') {
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

    hasExplicitResumeTarget(payload = {}) {
      if (!payload || typeof payload !== 'object') return false;
      return !!String(payload.resume_session_id || payload.continue_task || '').trim();
    },

    async fetchInterruptedSessionSnapshot(projectId = null) {
      const scopedProjectId = String(projectId == null ? '' : projectId).trim();
      const params = scopedProjectId ? `?project_id=${encodeURIComponent(scopedProjectId)}` : '';
      const data = await this.api('GET', `/api/agent/sessions/interrupted${params}`);
      return data?.session || null;
    },

    isPinnedWorkspaceConsole() {
      return !!String(this.windowPinnedProjectId || '').trim();
    },

    sharedConsoleCanAutoRestoreWorkspace() {
      return !this.isPinnedWorkspaceConsole();
    },

    newestRestorableAutoSession(sessions = []) {
      const rows = Array.isArray(sessions) ? sessions : [];
      return rows
        .filter(item => ['running', 'approval_required'].includes(String(item?.status || '').trim().toLowerCase()))
        .sort((a, b) => this.resumeTimestamp(b?.updated_at || b?.created_at) - this.resumeTimestamp(a?.updated_at || a?.created_at))[0] || null;
    },

    chooseInitialWorkspaceRestoreCandidate({ autoSessions = [], interruptedSession = null, savedProjectId = '' } = {}) {
      if (!this.sharedConsoleCanAutoRestoreWorkspace()) return null;

      const autoSession = this.newestRestorableAutoSession(autoSessions);
      const autoWorkspaceId = String(autoSession?.workspace_id || '').trim();
      if (autoWorkspaceId) {
        return {
          workspaceId: autoWorkspaceId,
          source: 'auto_session',
          label: this.workspaceTabLabel?.(autoWorkspaceId) || autoSession?.workspace_name || `Workspace ${autoWorkspaceId}`,
          reason: `Restored ${this.workspaceTabLabel?.(autoWorkspaceId) || autoSession?.workspace_name || autoWorkspaceId} because it has the latest active run.`,
        };
      }

      const interruptedWorkspaceId = String(interruptedSession?.workspace_id || '').trim();
      if (interruptedWorkspaceId) {
        return {
          workspaceId: interruptedWorkspaceId,
          source: 'interrupted_session',
          label: this.workspaceTabLabel?.(interruptedWorkspaceId) || interruptedSession?.project_name || `Workspace ${interruptedWorkspaceId}`,
          reason: `Restored ${this.workspaceTabLabel?.(interruptedWorkspaceId) || interruptedSession?.project_name || interruptedWorkspaceId} because it has the latest paused task.`,
        };
      }

      const saved = String(savedProjectId || '').trim();
      if (saved) {
        return {
          workspaceId: saved,
          source: 'saved_workspace',
          label: this.workspaceTabLabel?.(saved) || `Workspace ${saved}`,
          reason: '',
        };
      }
      return null;
    },

    applyInitialWorkspaceRestore(candidate = null, options = {}) {
      const workspaceId = String(candidate?.workspaceId || options?.savedProjectId || '').trim();
      if (!workspaceId) return '';
      this.ensureWorkspaceTab?.(workspaceId);
      this.chatProjectId = workspaceId;
      if (candidate?.reason) {
        this._workspaceRestoreReason = candidate.reason;
      }
      return workspaceId;
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

    prepareInterruptedSessionResume() {
      this.resumeBannerDismissed = true;
      this.removeInterruptedSessionMessages();
    },

    interruptedSessionWorkspaceId(session = null, autoSession = null) {
      return axonResolveResumeWorkspaceId(
        session || this.interruptedSession,
        autoSession || null,
        this.chatProjectId || '',
      );
    },

    interruptedSessionWorkspaceName(session = null, autoSession = null) {
      const item = session || this.interruptedSession || null;
      const workspaceId = this.interruptedSessionWorkspaceId(item, autoSession);
      if (!workspaceId) return String(item?.project_name || '').trim();
      const project = (this.projects || []).find(entry => String(entry?.id || '') === workspaceId);
      const label = String(project?.name || item?.project_name || '').trim();
      return label || `Workspace ${workspaceId}`;
    },

    resumeActionLabel(session = null, autoSession = null) {
      return axonResumeActionLabel(this.interruptedSessionWorkspaceName(session, autoSession));
    },

    syncInterruptedSessionWorkspace(session = null, options = {}) {
      const workspaceId = this.interruptedSessionWorkspaceId(session);
      if (!workspaceId) return '';
      this.ensureWorkspaceTab?.(workspaceId);
      if (options?.activate && String(this.chatProjectId || '').trim() !== workspaceId) {
        this.activateWorkspaceTab?.(workspaceId);
      }
      return workspaceId;
    },

    async checkInterruptedSession(options = {}) {
      if (this._interruptedSessionLoading) return;
      this._interruptedSessionLoading = true;
      const scopeKey = String(this.chatProjectId || '').trim() || 'all';
      const requestSeq = Number(this._interruptedSessionRequestSeq || 0) + 1;
      this._interruptedSessionRequestSeq = requestSeq;
      try {
        const session = await this.fetchInterruptedSessionSnapshot(this.chatProjectId || null);
        if (requestSeq !== this._interruptedSessionRequestSeq || this._chatHistoryScopeKey !== scopeKey) return;
        this.interruptedSession = session || null;
        if (this.interruptedSession?.status === 'approval_required') {
          this.syncPendingAgentApproval(
            this.interruptedSession.approval || { message: this.interruptedSession.last_error || '' },
            this.interruptedSession,
          );
        } else {
          this.clearPendingAgentApproval();
        }
        this.syncInterruptedSessionWorkspace(this.interruptedSession);
        this.resumeBannerDismissed = false;
        this.injectInterruptedSessionMessage();
      } catch (e) {
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
      const workspace = this.interruptedSessionWorkspaceName(session);
      const workspaceLine = workspace ? `Workspace: **${workspace}**\n\n` : '';
      if (assistant) return assistant;
      if (session.status === 'approval_required') {
        const approval = session.approval || {};
        const detail = approval.message || 'Approval is required before Axon can continue this task.';
        return `⚠️ ${detail}\n\n${workspaceLine}Task: **${task}**`;
      }
      if (error) {
        return `⚠️ Agent error: ${error}\n\n${workspaceLine}Task: **${task}**\n\nReload restored the paused session. Use **Continue** or say **please continue** to continue from here.`;
      }
      return `⚠️ This agent session was interrupted before it finished.\n\n${workspaceLine}Task: **${task}**\n\nUse **Continue** or say **please continue** to continue from here.`;
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
      const workspaceId = this.interruptedSessionWorkspaceId(session);
      const workspaceProjectId = parseInt(workspaceId, 10) || null;
      if (session && session.session_id) {
        return {
          resume_session_id: session.session_id,
          resume_reason: source,
          project_id: workspaceProjectId,
        };
      }
      const fallback = this.lastContinuableTask();
      if (!fallback?.task) return {};
      return {
        continue_task: fallback.task,
        resume_reason: `${source}:${fallback.source}`,
        project_id: workspaceProjectId,
      };
    },

    async continueRestoredSession(options = {}) {
      const message = String(options?.message || 'please continue').trim() || 'please continue';
      const source = String(options?.source || 'resume_banner').trim() || 'resume_banner';
      if (this.currentWorkspaceRunActive?.()) return false;
      const session = options?.session || this.interruptedSession || null;
      const workspaceId = this.interruptedSessionWorkspaceId(session);
      if (workspaceId && options?.activateWorkspace !== false) {
        this.syncInterruptedSessionWorkspace(session, { activate: true });
        if (typeof this.$nextTick === 'function') await this.$nextTick();
      }
      const resumePayload = {
        ...this.resumePayload(message, source),
        ...((options?.resumePayload && typeof options.resumePayload === 'object') ? options.resumePayload : {}),
      };
      if (workspaceId && !String(resumePayload.project_id || '').trim()) {
        const projectId = parseInt(workspaceId, 10) || null;
        if (projectId) resumePayload.project_id = projectId;
      }
      if (options?.clearNotice !== false) this.removeInterruptedSessionMessages();
      if (options?.dismissBanner !== false) this.resumeBannerDismissed = true;
      await this.sendChatSilent(message, 'agent', resumePayload);
      return true;
    },

    async quickResume() {
      if (this.currentWorkspaceRunActive?.()) return;
      const session = this.interruptedSession || null;
      const autoSession = session ? null : this.preferredResumeAutoSession('please continue', 'quick_resume');
      const workspaceId = this.interruptedSessionWorkspaceId(session, autoSession);
      if (workspaceId) {
        this.syncInterruptedSessionWorkspace(session || autoSession, { activate: true });
        if (typeof this.$nextTick === 'function') await this.$nextTick();
      }
      if (autoSession?.session_id) {
        if (String(this.chatProjectId || '') !== String(autoSession.workspace_id || '')) {
          this.activateWorkspaceTab?.(autoSession.workspace_id || '');
          if (typeof this.$nextTick === 'function') await this.$nextTick();
        }
        if (this.currentBackendSupportsAgent()) this.setConversationModeAuto({ persist: false });
        this.resumeBannerDismissed = true;
        await this.continueAutoSession(autoSession.session_id, {
          message: 'please continue',
          workspaceId: String(autoSession.workspace_id || workspaceId || '').trim(),
        });
        return;
      }
      await this.continueRestoredSession({ message: 'please continue', source: 'resume_banner', activateWorkspace: true });
    },
  };
}

window.axonResolveResumeWorkspaceId = axonResolveResumeWorkspaceId;
window.axonResumeActionLabel = axonResumeActionLabel;
window.axonChatResumeMixin = axonChatResumeMixin;
