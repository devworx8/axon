/* ══════════════════════════════════════════════════════════════
   Axon — Vercel Deploy Guidance
   ══════════════════════════════════════════════════════════════ */

function axonChatDeployGuidanceMixin() {
  const normalize = (value) => String(value || '').trim();

  return {
    deployLanePreparing: false,

    latestUserChatMessageText() {
      const rows = Array.isArray(this.chatMessages) ? [...this.chatMessages] : [];
      for (let index = rows.length - 1; index >= 0; index -= 1) {
        const item = rows[index] || {};
        if (String(item.role || '').toLowerCase() !== 'user') continue;
        const content = normalize(item.content);
        if (content) return content;
      }
      return '';
    },

    vercelDeployIntentSeedText(message = '') {
      const explicit = normalize(message);
      if (explicit) return explicit;
      const draft = normalize(this.chatInput);
      if (draft) return draft;
      return this.latestUserChatMessageText?.() || '';
    },

    looksLikeVercelDeployIntent(message = '') {
      const lowered = this.vercelDeployIntentSeedText?.(message).toLowerCase() || '';
      if (!lowered) return false;
      const mentionsVercel = /\bvercel\b/.test(lowered);
      const deployAction = /\b(deploy|deployment|ship|publish|promote|rollback|preview|production|domain)\b/.test(lowered);
      const startProject = /\b(start|create|setup|set up|launch|spin up)\b/.test(lowered) && /\bproject\b/.test(lowered);
      return mentionsVercel && (deployAction || startProject);
    },

    vercelDeployLaneReady() {
      return this.activePrimaryConversationMode?.() === 'agent'
        && this.currentRuntimeBackend?.() === 'cli'
        && this.permissionPresetKey?.() === 'full_access';
    },

    vercelDeployWorkspaceLabel() {
      return normalize(this.chatProject?.name || this.workspaceTabLabel?.(this.chatProjectId || '')) || 'the selected workspace';
    },

    vercelDeployLaneChecks() {
      const workspaceId = normalize(this.chatProjectId);
      const mode = this.activePrimaryConversationMode?.() || 'ask';
      const backend = this.currentRuntimeBackend?.() || 'api';
      const permission = this.permissionPresetKey?.() || 'default';
      return [
        {
          id: 'workspace',
          label: 'Workspace',
          ready: !!workspaceId,
          detail: workspaceId ? this.vercelDeployWorkspaceLabel() : 'Select a workspace',
        },
        {
          id: 'mode',
          label: 'Mode',
          ready: mode === 'agent',
          detail: mode === 'agent' ? 'Agent' : 'Switch to Agent',
        },
        {
          id: 'runtime',
          label: 'Runtime',
          ready: backend === 'cli',
          detail: backend === 'cli' ? (this.currentCliRuntimeModel?.() || 'CLI Agent') : 'Switch to CLI Agent',
        },
        {
          id: 'permissions',
          label: 'Permissions',
          ready: permission === 'full_access',
          detail: permission === 'full_access' ? 'Full access' : 'Enable Full access',
        },
      ];
    },

    vercelDeployGuidanceVisible(message = '') {
      return !!this.looksLikeVercelDeployIntent?.(message);
    },

    vercelDeployGuidanceSummary() {
      const workspace = this.vercelDeployWorkspaceLabel?.() || 'the selected workspace';
      if (this.vercelDeployLaneReady?.()) {
        return `${workspace} is armed for real Vercel work. Axon will operate from Agent mode on CLI with full access, not the isolated Autonomous worktree lane.`;
      }
      return 'Real Vercel start and deploy work runs from Agent mode on CLI with Full access. Autonomous stays in the isolated worktree lane for safe worktree execution.';
    },

    vercelDeployGuidanceState(message = '') {
      const visible = this.vercelDeployGuidanceVisible?.(message);
      const ready = this.vercelDeployLaneReady?.();
      return {
        visible,
        ready,
        summary: this.vercelDeployGuidanceSummary?.() || '',
        checks: this.vercelDeployLaneChecks?.() || [],
      };
    },

    vercelDeployPrompt(kind = 'deploy') {
      const workspace = this.vercelDeployWorkspaceLabel?.() || 'the selected workspace';
      if (String(kind || '').trim().toLowerCase() === 'rollback') {
        return `Rollback the Vercel deployment for ${workspace} from the real workspace, then report the restored deployment, live URL, and any blockers.`;
      }
      return `Start or link the Vercel project for ${workspace}, deploy it from the real workspace, and report the live URL, environment changes, and any blockers.`;
    },

    focusChatComposer() {
      this.$nextTick?.(() => this.$refs?.chatComposer?.focus?.());
    },

    async draftVercelDeployPrompt(kind = 'deploy') {
      const nextPrompt = this.vercelDeployPrompt?.(kind) || '';
      if (!normalize(nextPrompt)) return false;
      this.chatInput = nextPrompt;
      this.focusChatComposer?.();
      return true;
    },

    async prepareVercelDeployLane(options = {}) {
      if (this.deployLanePreparing) return false;
      const workspaceId = normalize(options.workspaceId || this.chatProjectId);
      if (!workspaceId) {
        this.showToast?.('Select a workspace before arming the Vercel deploy lane.');
        return false;
      }

      this.deployLanePreparing = true;
      try {
        this.switchTab?.('chat');
        if (this.activePrimaryConversationMode?.() !== 'agent') this.chooseConversationModeAgent?.();
        if (this.currentRuntimeBackend?.() !== 'cli') {
          await this.applyCliRuntimeModel?.(this.currentCliRuntimeModel?.() || this.runtimeStatus?.cli_model || '');
        }
        if (this.permissionPresetKey?.() !== 'full_access') {
          await this.setPermissionPreset?.('full_access');
        }

        const ready = !!this.vercelDeployLaneReady?.();
        if (ready) {
          if (options.prefillPrompt !== false && !normalize(this.chatInput)) {
            await this.draftVercelDeployPrompt?.(options.kind || 'deploy');
          } else {
            this.focusChatComposer?.();
          }
          this.showToast?.('Deploy lane ready: Agent + CLI + Full access.');
          return true;
        }

        this.showToast?.('Deploy lane setup is incomplete. Review mode, runtime, and permissions.');
        return false;
      } catch (e) {
        this.showToast?.(`Could not arm the deploy lane: ${e?.message || e}`);
        return false;
      } finally {
        this.deployLanePreparing = false;
      }
    },
  };
}

window.axonChatDeployGuidanceMixin = axonChatDeployGuidanceMixin;
