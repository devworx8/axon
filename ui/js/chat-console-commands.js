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
      this.rememberComposerHistory?.(spec.message || message);
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

    async sendChatSilent(message, forceMode, extraPayload = {}) {
      const msg = String(message || '').trim();
      if (!msg) return;
      const workspaceId = String(this.chatProjectId || '').trim();
      const started = Date.now();
      while (this.currentWorkspaceRunActive?.() && (Date.now() - started) < 5000) {
        await new Promise(resolve => setTimeout(resolve, 120));
      }
      if (this.currentWorkspaceRunActive?.()) {
        this.showToast?.('Axon is still finishing the previous step. Try continue again in a moment.');
        return;
      }

      const mode = forceMode
        || this.effectiveChatMode?.(msg, forceMode)
        || this.resolveChatMode?.(msg)
        || 'chat';
      const explicitResumeTarget = this.hasExplicitResumeTarget?.(extraPayload);
      const autoResumeSession = mode === 'agent' && !explicitResumeTarget
        ? this.preferredResumeAutoSession?.(msg, extraPayload?.resume_reason || 'resume')
        : null;

      if (autoResumeSession?.session_id && this.currentBackendSupportsAgent?.()) {
        this.setConversationModeAuto?.({ persist: false });
      }
      this.setWorkspaceRunLoading?.(workspaceId, true);
      if (typeof this.setWorkspaceRunLoading !== 'function') this.chatLoading = true;
      this.beginLiveOperator?.(mode, msg, workspaceId);

      const finishRun = () => {
        this.setWorkspaceRunLoading?.(workspaceId, false);
        if (typeof this.setWorkspaceRunLoading !== 'function') this.chatLoading = false;
        this.scrollChat?.();
        this._processQueue?.();
      };
      const appendError = (error) => {
        this.chatMessages = Array.isArray(this.chatMessages) ? this.chatMessages : [];
        this.chatMessages.push({
          id: Date.now() + 1,
          role: 'assistant',
          content: `⚠️ ${error?.message || error || 'Auto mode error'}`,
          created_at: new Date().toISOString(),
          mode: 'agent',
          threadMode: 'recover',
          error: true,
          retryMsg: msg,
          resources: [],
        });
      };

      if (autoResumeSession?.session_id) {
        try {
          if (String(this.chatProjectId || '').trim() !== String(autoResumeSession.workspace_id || '').trim()) {
            this.activateWorkspaceTab?.(autoResumeSession.workspace_id || '');
            await this.$nextTick?.();
          }
          await this.continueAutoSession?.(autoResumeSession.session_id, {
            message: msg,
            workspaceId: String(autoResumeSession.workspace_id || '').trim(),
          });
        } catch (error) {
          appendError(error);
        }
        finishRun();
        return;
      }

      if (mode === 'agent' && this.autonomousConsoleActive?.()) {
        try {
          const currentAuto = this.currentWorkspaceAutoSession?.() || null;
          if (this.isExplicitResumeText?.(msg) && currentAuto?.session_id) {
            await this.continueAutoSession?.(currentAuto.session_id, {
              message: msg,
              workspaceId: String(currentAuto.workspace_id || workspaceId || '').trim(),
            });
          } else {
            await this.startAutoSessionFromChat?.(
              msg,
              [],
              this.normalizedComposerOptions?.() || {},
              { workspaceId },
            );
          }
        } catch (error) {
          appendError(error);
        }
        finishRun();
        return;
      }

      const respId = Date.now() + 1;
      const placeholder = this.createAssistantPlaceholder
        ? this.createAssistantPlaceholder(respId, mode, [])
        : {
            id: respId,
            role: 'assistant',
            content: '',
            streaming: true,
            created_at: new Date().toISOString(),
            mode,
            resources: [],
          };
      this.chatMessages = Array.isArray(this.chatMessages) ? this.chatMessages : [];
      this.chatMessages.push(placeholder);
      this.scrollChat?.();

      try {
        await this.streamChatMessage?.(msg, mode, respId, [], extraPayload);
      } catch (error) {
        if (error?.name === 'AbortError') {
          finishRun();
          return;
        }
        const idx = this.chatMessages.findIndex(messageRow => messageRow.id === respId);
        if (idx >= 0) {
          this.chatMessages[idx].content = `⚠️ ${error?.message || error}`;
          this.chatMessages[idx].streaming = false;
          this.chatMessages[idx].error = true;
        }
      }

      finishRun();
    },
  };
}

window.axonChatConsoleCommandsMixin = axonChatConsoleCommandsMixin;
