function axonChatApprovalMixin() {
  return {
    currentPendingAgentApproval() {
      const pending = this.pendingAgentApproval;
      if (!pending || typeof pending !== 'object') return null;
      const currentWorkspaceId = String(this.chatProjectId || '').trim();
      const pendingWorkspaceId = String(pending.workspaceId || '').trim();
      if (!pendingWorkspaceId || !currentWorkspaceId || pendingWorkspaceId === currentWorkspaceId) {
        return pending;
      }
      return null;
    },

    syncPendingAgentApproval(approval = {}, session = null) {
      const payload = approval && typeof approval === 'object' ? approval : {};
      const action = payload.approval_action && typeof payload.approval_action === 'object'
        ? { ...payload.approval_action }
        : (payload.action && typeof payload.action === 'object' ? { ...payload.action } : null);
      const workspaceId = String(
        payload.workspace_id
        || session?.workspace_id
        || session?.workspaceId
        || this.chatProjectId
        || ''
      ).trim();
      const workspaceName = String(
        payload.project_name
        || payload.workspace_name
        || session?.project_name
        || session?.workspace_name
        || this.workspaceTabLabel?.(workspaceId)
        || ''
      ).trim();
      const sessionId = String(
        action?.session_id
        || payload.session_id
        || session?.session_id
        || ''
      ).trim();
      this.pendingAgentApproval = {
        id: String(payload.action_fingerprint || action?.action_fingerprint || `approval-${Date.now()}`),
        workspaceId,
        workspaceName,
        sessionId,
        message: String(payload.message || 'Approval is required before Axon can continue.').trim(),
        summary: String(payload.summary || action?.summary || '').trim(),
        commandPreview: String(payload.full_command || action?.command_preview || '').trim(),
        commandName: String(payload.command || '').trim(),
        kind: String(payload.kind || '').trim() || 'command',
        draftCommitMessage: String(payload.draft_commit_message || '').trim(),
        resumeTask: String(payload.resume_task || '').trim(),
        scopeOptions: Array.isArray(payload.scope_options)
          ? [...payload.scope_options]
          : (Array.isArray(action?.scope_options) ? [...action.scope_options] : ['once']),
        persistAllowed: Boolean(
          payload.persist_allowed != null ? payload.persist_allowed : action?.persist_allowed
        ),
        action,
      };
      if (workspaceId) this.ensureWorkspaceTab?.(workspaceId);
    },

    clearPendingAgentApproval(options = {}) {
      const current = this.pendingAgentApproval;
      if (!current) return;
      const workspaceId = String(options.workspaceId || options.workspace_id || '').trim();
      const sessionId = String(options.sessionId || options.session_id || '').trim();
      if (workspaceId && String(current.workspaceId || '').trim() !== workspaceId) return;
      if (sessionId && String(current.sessionId || '').trim() !== sessionId) return;
      this.pendingAgentApproval = null;
    },

    dismissPendingAgentApproval() {
      this.clearPendingAgentApproval();
    },

    approvalSupportsScope(pending = null, scope = 'once') {
      const item = pending || this.currentPendingAgentApproval?.() || null;
      if (!item) return false;
      return (item.scopeOptions || []).includes(String(scope || 'once').trim().toLowerCase());
    },

    approvalCommandPreview(pending = null) {
      const item = pending || this.currentPendingAgentApproval?.() || null;
      if (!item) return '';
      if (item.commandPreview) return item.commandPreview;
      return String(item.action?.command_preview || '').trim();
    },

    async approvePendingAgentAction(scope = 'once') {
      const pending = this.currentPendingAgentApproval?.() || this.pendingAgentApproval || null;
      if (!pending?.action?.action_fingerprint || this.approvalActionBusy) return null;

      const requestedScope = this.approvalSupportsScope(pending, scope) ? scope : 'once';
      this.approvalActionBusy = true;
      try {
        await this.api('POST', '/api/agent/approve-action', {
          action: pending.action,
          scope: requestedScope,
          session_id: pending.sessionId || '',
        });

        const workspaceId = String(pending.workspaceId || this.chatProjectId || '').trim();
        if (workspaceId && workspaceId !== String(this.chatProjectId || '').trim()) {
          this.activateWorkspaceTab?.(workspaceId);
          await this.$nextTick?.();
        }

        const resumeMessage = String(pending.resumeTask || 'please continue').trim();
        await this.sendChatSilent?.(resumeMessage, 'agent', {
          resume_session_id: pending.sessionId || '',
          project_id: workspaceId ? parseInt(workspaceId, 10) : null,
          resume_reason: 'approval_continue',
        });
        this.clearPendingAgentApproval({
          workspaceId,
          sessionId: pending.sessionId || '',
        });
        this.showToast?.('Approval granted. Axon is continuing the paused task.');
        return true;
      } catch (error) {
        this.showToast?.(error?.message || 'Approval failed');
        return false;
      } finally {
        this.approvalActionBusy = false;
      }
    },
  };
}

window.axonChatApprovalMixin = axonChatApprovalMixin;
