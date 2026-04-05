function axonChatSlashCommandsMixin() {
  const MODE_COMMANDS = {
    '/ask': { label: 'Ask mode', run(app) { app.chooseConversationModeAsk?.(); } },
    '/auto': { label: 'Autonomous mode', run(app) { app.chooseConversationModeAuto?.(); } },
    '/agent': { label: 'Agent mode', run(app) { app.chooseConversationModeAgent?.(); } },
    '/code': { label: 'Code mode', run(app) { app.chooseConversationModeCode?.(); } },
    '/research': { label: 'Research mode', run(app) { app.chooseConversationModeResearch?.(); } },
  };

  const helperCopy = () => [
    'Slash commands:',
    '- `/help` show the command palette',
    '- `/ask`, `/agent`, `/auto`, `/code`, `/research` switch Axon modes',
    '- `/voice` open the voice command center and arm auto-speak',
    '- `/deploy` prepare the real deploy lane',
    '- `/preview` start or attach the live preview panel',
    '- `/status` show the active workspace, runtime, and permission posture',
  ].join('\n');

  return {
    slashCommandHelpText() {
      return helperCopy();
    },

    _resetSlashComposerState() {
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
    },

    _appendSlashUserMessage(content, createdAt = '') {
      this.chatMessages = Array.isArray(this.chatMessages) ? this.chatMessages : [];
      this.chatMessages.push({
        id: Date.now(),
        role: 'user',
        content: String(content || '').trim(),
        created_at: createdAt || new Date().toISOString(),
        mode: 'chat',
        threadMode: 'ask',
        resources: [],
      });
    },

    _appendSlashAssistantMessage(content, createdAt = '') {
      this.chatMessages = Array.isArray(this.chatMessages) ? this.chatMessages : [];
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

    slashStatusSummary() {
      const workspace = this.workspaceTabLabel?.()
        || this.chatProject?.name
        || (this.chatProjectId ? `Workspace #${this.chatProjectId}` : 'All workspaces');
      const mode = this.activePrimaryConversationMode?.() || 'ask';
      const runtime = this.assistantRuntimeLabel?.()
        || this.activeChatModel?.()
        || this.currentRuntimeBackend?.()
        || 'runtime unavailable';
      const permissions = this.permissionPresetLabel?.() || 'Default permissions';
      return [
        `Workspace: ${workspace}`,
        `Mode: ${mode}`,
        `Runtime: ${runtime}`,
        `Permissions: ${permissions}`,
      ].join('\n');
    },

    async maybeHandleSlashCommand(message = '') {
      const text = String(message || '').trim();
      if (!text.startsWith('/')) return false;
      const parts = text.split(/\s+/).filter(Boolean);
      const command = String(parts[0] || '/').toLowerCase();
      if (['/login', '/login-cli', '/install', '/install-cli'].includes(command)) return false;

      const now = new Date().toISOString();
      this.rememberComposerHistory?.(text);
      this._resetSlashComposerState?.();
      this._appendSlashUserMessage?.(text, now);

      let response = '';
      if (command === '/' || command === '/help') {
        response = this.slashCommandHelpText?.() || helperCopy();
      } else if (MODE_COMMANDS[command]) {
        MODE_COMMANDS[command].run(this);
        response = `${MODE_COMMANDS[command].label} armed.`;
      } else if (command === '/voice') {
        this.openVoiceCommandCenter?.();
        if (this.voiceOutputAvailable?.()) this.voiceMode = true;
        response = this.voiceOutputAvailable?.()
          ? 'Voice command center opened. Auto-speak is armed.'
          : 'Voice command center opened. Speech output is not available in this browser yet.';
      } else if (command === '/deploy') {
        if (typeof this.prepareVercelDeployLane === 'function') {
          const prepared = await this.prepareVercelDeployLane();
          response = prepared
            ? 'Deploy lane prepared. Axon is on Agent + CLI + Full access and the deploy prompt is ready.'
            : 'Deploy lane could not be prepared right now.';
        } else {
          response = 'Deploy lane helper is not available in this shell.';
        }
      } else if (command === '/preview') {
        if (!this.chatProjectId) {
          response = 'Select a workspace first, then run `/preview` again.';
        } else if (typeof this.ensureWorkspacePreview === 'function') {
          await this.ensureWorkspacePreview({ openExternal: false, attachBrowser: true, silent: true });
          response = 'Live preview panel is starting for the current workspace.';
        } else {
          response = 'Live preview is not available in this shell.';
        }
      } else if (command === '/status') {
        response = this.slashStatusSummary?.() || 'Status unavailable.';
      } else {
        response = `Unknown slash command: ${command}\n\n${this.slashCommandHelpText?.() || helperCopy()}`;
      }

      this._appendSlashAssistantMessage?.(response, now);
      this.scrollChat?.();
      return true;
    },
  };
}

window.axonChatSlashCommandsMixin = axonChatSlashCommandsMixin;
