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
  };
}

window.axonChatAutoStreamMixin = axonChatAutoStreamMixin;
