function axonChatConsoleCommandsMixin() {
  return {
    chatConsoleCommandSpec(message = '') {
      const text = String(message || '').trim();
      if (!text.startsWith('/')) return null;
      const parts = text.split(/\s+/).filter(Boolean);
      const command = String(parts[0] || '').toLowerCase();
      if (!['/login', '/login-cli', '/install', '/install-cli'].includes(command)) return null;
      return { type: 'console_command', command, message: text };
    },

    _appendConsoleCommandAssistantMessage(content, createdAt = '') {
      this.chatMessages.push({
        id: Date.now() + 1,
        role: 'assistant',
        content: String(content || '').trim(),
        created_at: createdAt || new Date().toISOString(),
        mode: 'chat',
        threadMode: 'ask',
        resources: [],
      });
    },

    openRuntimeLoginModalFromConsoleSession(session = null, family = '') {
      const familyName = String(family || session?.family || '').trim().toLowerCase();
      if (!familyName || !session) return;
      if (this.runtimeLoginModal?.pollHandle) clearTimeout(this.runtimeLoginModal.pollHandle);
      this.runtimeLoginModal = {
        open: true,
        family: familyName,
        session,
        loading: false,
        error: '',
        autoOpenedUrl: '',
        pollHandle: null,
      };
      this._maybeOpenRuntimeLoginBrowser?.(session);
      if (this.runtimeLoginPendingStatus?.(session?.status)) this._scheduleRuntimeLoginPoll?.();
    },

    async maybeHandleInteractiveConsoleCommand(message = '') {
      const spec = this.chatConsoleCommandSpec?.(message);
      if (!spec) return false;

      const now = new Date().toISOString();
      this.chatInput = '';
      this.followUpSuggestions = [];
      this._userScrolled = false;
      if (this.slashMenu) {
        this.slashMenu.open = false;
        this.slashMenu.query = '';
        this.slashMenu.filtered = [];
        this.slashMenu.selectedIdx = 0;
      }
      if (!this.composerOptions?.pin_context) this.selectedResources = [];
      this.showResourcePicker = false;
      this.showComposerMenu = false;
      this.resetChatComposerHeight?.();
      this.chatMessages.push({
        id: Date.now(),
        role: 'user',
        content: String(spec.message || message || '').trim(),
        created_at: now,
        mode: 'chat',
        threadMode: 'ask',
        resources: [],
      });
      const workspaceId = String(this.chatProjectId || '').trim();
      this.setWorkspaceRunLoading?.(workspaceId, true);
      this.beginLiveOperator?.('chat', message, workspaceId);
      this.scrollChat?.();

      try {
        const result = await this.api('POST', '/api/chat', {
          message: spec.message,
          project_id: this.chatProjectId ? parseInt(this.chatProjectId, 10) : null,
        });
        this._appendConsoleCommandAssistantMessage(
          result?.response || 'Console command completed.',
          now,
        );
        if (result?.console_command && result?.runtime_login_session) {
          this.openRuntimeLoginModalFromConsoleSession(
            result.runtime_login_session,
            result.family || result.runtime_login_session?.family || '',
          );
        }
        if (result?.console_command && ['install', 'login'].includes(String(result.command || '').toLowerCase())) {
          await this.loadRuntimeStatus?.();
        }
      } catch (e) {
        this._appendConsoleCommandAssistantMessage(
          `⚠️ ${e?.message || 'Could not start the runtime sign-in flow.'}`,
          now,
        );
      }

      this.setWorkspaceRunLoading?.(workspaceId, false);
      this.clearLiveOperator?.(1200, workspaceId);
      this.scrollChat?.();
      this._processQueue?.();
      return true;
    },
  };
}

window.axonChatConsoleCommandsMixin = axonChatConsoleCommandsMixin;
