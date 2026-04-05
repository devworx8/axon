/* ══════════════════════════════════════════════════════════════
   Axon — Chat Auto Stream
   ══════════════════════════════════════════════════════════════ */

function axonChatAutoStreamMixin() {
  const RECOVER_STATUSES = new Set(['approval_required', 'error']);

  const statusLabel = (status = '') => {
    const key = String(status || '').trim().toLowerCase();
    if (key === 'review_ready') return 'ready for review';
    if (key === 'approval_required') return 'paused for approval';
    if (key === 'error') return 'paused after an error';
    if (key === 'applied') return 'applied';
    if (key === 'discarded') return 'discarded';
    return 'running';
  };

  return {
    autoSessionTimelineBlocks(session = null) {
      if (!session) return { thinkingBlocks: [], workingBlocks: [] };
      const rows = Array.isArray(this.autoSessionLiveFeed?.(session))
        ? this.autoSessionLiveFeed(session)
        : [];
      const createdAt = String(session.updated_at || session.created_at || new Date().toISOString());
      const blocks = rows.map((entry, index) => ({
        id: `auto-step-${String(session.session_id || '')}-${index}-${String(entry?.at || index)}`,
        name: 'auto_step',
        title: String(entry?.title || 'Auto step'),
        args: {},
        result: String(entry?.detail || '').trim(),
        evidenceSource: 'workspace',
        status: index === rows.length - 1 && String(session.status || '').trim().toLowerCase() === 'running' ? 'running' : 'done',
        order: index + 1,
        createdAt: String(entry?.at || createdAt),
        updatedAt: String(entry?.at || createdAt),
      }));

      if (!blocks.length) {
        const status = String(session.status || '').trim().toLowerCase();
        const fallbackTitle = status === 'review_ready'
          ? 'Auto session ready for review'
          : status === 'approval_required'
            ? 'Auto session awaiting approval'
            : status === 'error'
              ? 'Auto session needs attention'
              : 'Running Auto session';
        const fallbackDetail = String(session.detail || session.last_error || session.final_output || '').trim()
          || 'Axon is working in the sandbox and will stop at a reviewable handoff.';
        blocks.push({
          id: `auto-step-${String(session.session_id || '')}-fallback`,
          name: 'auto_step',
          title: fallbackTitle,
          args: {},
          result: fallbackDetail,
          evidenceSource: 'workspace',
          status: status === 'running' ? 'running' : 'done',
          order: 1,
          createdAt,
          updatedAt: createdAt,
        });
      }

      return {
        thinkingBlocks: [],
        workingBlocks: blocks,
      };
    },

    autoSessionMessageContent(session) {
      if (!session) return '';
      const title = String(session.title || 'Auto session').trim();
      const workspace = String(session.workspace_name || this.liveOperatorWorkspaceName?.() || 'this workspace').trim();
      const branch = String(session.branch_name || '').trim();
      const changed = Number(session.changed_files_count || 0);
      const summary = String(session.detail || session.last_error || session.final_output || '').trim();
      const status = String(session.status || '').trim().toLowerCase();
      const branchLine = branch ? ` on branch \`${branch}\`` : '';

      if (status === 'running') {
        return `🔄 I’m working on **${title}** in the sandbox for **${workspace}**${branchLine}.\n\n${summary || 'You can follow the live steps above while Axon works.'}`;
      }
      if (status === 'review_ready') {
        return `✅ **${title}** is ${statusLabel(status)} for **${workspace}**${branchLine}.\n\nChanged files: **${changed}**. Use **Report**, **Apply**, or **Discard** in the Auto panel.`;
      }
      if (status === 'approval_required') {
        return `⚠️ **${title}** is ${statusLabel(status)} for **${workspace}**${branchLine}.\n\n${summary || 'Approve the next step and Axon will continue from the same sandbox.'}`;
      }
      if (status === 'error') {
        return `⚠️ **${title}** is ${statusLabel(status)} for **${workspace}**${branchLine}.\n\n${summary || 'Axon did not reach a clean reviewable handoff yet.'}`;
      }
      if (status === 'applied') {
        return `✅ I applied **${title}** back to **${workspace}**${branchLine}.`;
      }
      if (status === 'discarded') {
        return `🗑 I discarded **${title}** for **${workspace}**${branchLine}.`;
      }
      return `🤖 **${title}** is ready for the next Auto step in **${workspace}**${branchLine}.`;
    },

    syncAutoSessionNoticeForCurrentWorkspace() {
      const workspaceId = String(this.chatProjectId || '').trim();
      const current = this.currentWorkspaceAutoSession?.() || null;
      const currentSessionId = String(current?.session_id || '').trim();

      this.chatMessages = (this.chatMessages || []).filter(message => {
        if (!message?.autoSessionNotice) return true;
        const messageWorkspace = String(message.autoSessionWorkspaceId || '').trim();
        const messageSessionId = String(message.autoSessionId || '').trim();
        if (!workspaceId || !currentSessionId) return false;
        return messageWorkspace === workspaceId && messageSessionId === currentSessionId;
      });

      if (!current || !workspaceId) return;

      const id = `auto-session-${current.session_id}`;
      const blocks = this.autoSessionTimelineBlocks(current);
      const runtime = current.runtime || {};
      const nextMessage = {
        id,
        role: 'assistant',
        content: this.autoSessionMessageContent(current),
        streaming: String(current.status || '').trim().toLowerCase() === 'running',
        created_at: current.updated_at || current.created_at || new Date().toISOString(),
        mode: 'agent',
        threadMode: this.autoSessionThreadMode?.(current) || (RECOVER_STATUSES.has(String(current.status || '').trim().toLowerCase()) ? 'recover' : 'auto'),
        autoSessionNotice: true,
        autoSessionWorkspaceId: workspaceId,
        autoSessionId: current.session_id,
        thinkingBlocks: blocks.thinkingBlocks,
        workingBlocks: blocks.workingBlocks,
        agentEvents: [],
        evidenceSources: ['workspace'],
        resources: [],
        modelLabel: [String(runtime.label || '').trim(), String(runtime.model || '').trim()].filter(Boolean).join(' · '),
      };

      const idx = (this.chatMessages || []).findIndex(message => message.id === id);
      if (idx >= 0) this.chatMessages[idx] = { ...this.chatMessages[idx], ...nextMessage };
      else this.chatMessages.push(nextMessage);

      this.$nextTick?.(() => requestAnimationFrame(() => this.scrollChat?.(true)));
    },

    maybeStartAutoWorkspacePreview(session = null) {
      const current = session || this.currentWorkspaceAutoSession?.();
      if (!current || !this.autonomousConsoleActive?.() || this.isMobile) return;
      const workspaceId = String(this.chatProjectId || '').trim();
      if (!workspaceId || String(current.workspace_id || '') !== workspaceId) return;
      if (this.currentWorkspacePreview?.()?.url || this.workspacePreview?.loading) return;
      const status = String(current.status || '').trim().toLowerCase();
      if (!['running', 'review_ready', 'approval_required'].includes(status)) return;
      const key = `${workspaceId}:${current.session_id}`;
      if (!this._autoPreviewAutostarted) this._autoPreviewAutostarted = {};
      if (this._autoPreviewAutostarted[key]) return;
      this._autoPreviewAutostarted[key] = true;
      queueMicrotask(() => this.ensureWorkspacePreview?.({ openExternal: false, attachBrowser: true, silent: true }));
    },

    autoSessionThreadMode(session = null) {
      const status = String(session?.status || '').trim().toLowerCase();
      return RECOVER_STATUSES.has(status) ? 'recover' : 'auto';
    },

    updateAutoSessionRecord(session = null) {
      if (!session?.session_id) return;
      const rows = Array.isArray(this.autoSessions) ? [...this.autoSessions] : [];
      const idx = rows.findIndex(item => String(item?.session_id || '') === String(session.session_id));
      if (idx >= 0) rows[idx] = { ...rows[idx], ...session };
      else rows.push({ ...session });
      this.autoSessions = this.sortAutoSessions?.(rows) || rows;
      if (this.autoSessionReview?.open && String(this.autoSessionReview?.session?.session_id || '') === String(session.session_id)) {
        this.autoSessionReview.session = { ...this.autoSessionReview.session, ...session };
      }
      this.syncAutoSessionNoticeForCurrentWorkspace?.();
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
      this.autoSessions = this.sortAutoSessions?.([...byId.values()]) || [...byId.values()];
      this.syncAutoSessionNoticeForCurrentWorkspace?.();
      const current = this.currentWorkspaceAutoSession?.() || null;
      if (current) this.maybeStartAutoWorkspacePreview?.(current);
    },

    async startAutoSessionFromChat(message, resourceIds = [], composerOptions = {}, options = {}) {
      const workspaceId = String(options?.workspaceId || this.chatProjectId || '').trim();
      if (!workspaceId) throw new Error('Select a workspace before starting Auto mode.');
      if (this.currentBackendSupportsAgent?.()) this.setConversationModeAuto?.({ persist: false });
      const payload = {
        message,
        project_id: parseInt(workspaceId, 10),
        resource_ids: resourceIds,
        composer_options: { ...(composerOptions || {}), agent_role: 'auto' },
        ...(this.autoSessionRuntimePayload?.() || {}),
      };
      const data = await this.api('POST', '/api/auto/start', payload);
      if (data?.session) this.updateAutoSessionRecord?.(data.session);
      this.loadWorkspacePreview?.();
      if (data?.requires_resolution) this.showToast?.('Finish the current Auto session first — continue, apply, or discard it.');
      else if (data?.already_running) this.showToast?.('Auto session already running');
      else if (data?.started) this.showToast?.('Auto session started');
      return data;
    },

    async continueAutoSession(sessionId = '', options = {}) {
      const current = this.currentWorkspaceAutoSession?.() || null;
      const target = String(sessionId || current?.session_id || '').trim();
      if (!target) {
        this.showToast?.('No Auto session to continue in this workspace');
        return null;
      }
      if (this.currentBackendSupportsAgent?.()) this.setConversationModeAuto?.({ persist: false });
      const workspaceId = String(options?.workspaceId || this.chatProjectId || current?.workspace_id || '').trim();
      const payload = {
        message: String(options?.message || 'please continue'),
        project_id: parseInt(workspaceId, 10) || null,
        composer_options: { ...(this.normalizedComposerOptions?.() || {}), agent_role: 'auto' },
        ...(this.autoSessionRuntimePayload?.() || {}),
      };
      const data = await this.api('POST', `/api/auto/${encodeURIComponent(target)}/continue`, payload);
      if (data?.session) this.updateAutoSessionRecord?.(data.session);
      this.loadWorkspacePreview?.();
      if (data?.already_running) this.showToast?.('Auto session already running');
      else if (data?.started) this.showToast?.('Auto session resumed');
      return data;
    },

    async applyAutoSession(sessionId = '') {
      const target = String(sessionId || this.currentWorkspaceAutoSession?.()?.session_id || '').trim();
      if (!target) return;
      if (typeof confirm === 'function' && !confirm('Apply this Auto session back to the source workspace?')) return;
      try {
        const data = await this.api('POST', `/api/auto/${encodeURIComponent(target)}/apply`);
        if (data?.session) this.updateAutoSessionRecord?.(data.session);
        this.loadWorkspacePreview?.();
        this.showToast?.(data?.summary || 'Auto session applied');
      } catch (e) {
        this.showToast?.(e.message || 'Failed to apply Auto session');
      }
    },

    async discardAutoSession(sessionId = '') {
      const target = String(sessionId || this.currentWorkspaceAutoSession?.()?.session_id || '').trim();
      if (!target) return;
      if (typeof confirm === 'function' && !confirm('Discard this Auto session and remove the sandbox worktree?')) return;
      try {
        await this.api('DELETE', `/api/auto/${encodeURIComponent(target)}`);
        this.autoSessions = (this.sortAutoSessions?.((this.autoSessions || []).filter(item => String(item?.session_id || '') !== target))
          || (this.autoSessions || []).filter(item => String(item?.session_id || '') !== target));
        this.loadWorkspacePreview?.();
        if (this.autoSessionReview?.open && String(this.autoSessionReview?.session?.session_id || '') === target) {
          this.autoSessionReview = { open: false, session: null };
        }
        this.syncAutoSessionNoticeForCurrentWorkspace?.();
        this.showToast?.('Auto session discarded');
      } catch (e) {
        this.showToast?.(e.message || 'Failed to discard Auto session');
      }
    },
  };
}

window.axonChatAutoStreamMixin = axonChatAutoStreamMixin;
