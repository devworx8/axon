/* ══════════════════════════════════════════════════════════════
   Axon — Vercel Deploy Guidance
   ══════════════════════════════════════════════════════════════ */

function axonChatDeployGuidanceMixin() {
  const normalize = (value) => String(value || '').trim();
  const terminalMode = (value) => String(value || 'read_only').trim().toLowerCase();

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

    deployIntentSeedText(message = '') {
      const explicit = normalize(message);
      if (explicit) return explicit;
      const draft = normalize(this.chatInput);
      if (draft) return draft;
      return this.latestUserChatMessageText?.() || '';
    },

    laneWorkspaceId(candidate = '') {
      return normalize(candidate || this.chatProjectId);
    },

    laneWorkspaceLabel() {
      return normalize(this.chatProject?.name || this.workspaceTabLabel?.(this.chatProjectId || '')) || 'the selected workspace';
    },

    terminalApprovalReady() {
      return terminalMode(this.settingsForm?.terminal_default_mode) === 'approval_required';
    },

    operatorLaneReady(options = {}) {
      const baseReady = this.activePrimaryConversationMode?.() === 'agent'
        && this.currentRuntimeBackend?.() === 'cli'
        && this.permissionPresetKey?.() === 'full_access';
      if (!baseReady) return false;
      return options.requireTerminalApproval ? this.terminalApprovalReady?.() : true;
    },

    operatorLaneChecks(options = {}) {
      const workspaceId = this.laneWorkspaceId?.(options.workspaceId);
      const mode = this.activePrimaryConversationMode?.() || 'ask';
      const backend = this.currentRuntimeBackend?.() || 'api';
      const permission = this.permissionPresetKey?.() || 'default';
      const checks = [
        {
          id: 'workspace',
          label: 'Workspace',
          ready: !!workspaceId,
          detail: workspaceId ? this.laneWorkspaceLabel?.() : 'Select a workspace',
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
      if (options.requireTerminalApproval) {
        checks.push({
          id: 'terminal',
          label: 'Terminal',
          ready: this.terminalApprovalReady?.(),
          detail: this.terminalApprovalReady?.() ? 'Approval required' : 'Set to Approval required',
        });
      }
      return checks;
    },

    async ensureTerminalDefaultMode(mode = 'approval_required') {
      const normalized = terminalMode(mode);
      if (this.terminalApprovalReady?.() && normalized === 'approval_required') return true;
      this.settingsForm = this.settingsForm || {};
      const previous = this.settingsForm.terminal_default_mode || 'read_only';
      try {
        if (typeof this.api === 'function') {
          await this.api('POST', '/api/settings', {
            terminal_default_mode: normalized,
          });
        }
        this.settingsForm.terminal_default_mode = normalized;
        await this.loadRuntimeStatus?.();
        return terminalMode(this.settingsForm.terminal_default_mode) === normalized;
      } catch (e) {
        this.settingsForm.terminal_default_mode = previous;
        throw e;
      }
    },

    async prepareOperationalLane(options = {}) {
      if (this.deployLanePreparing) return false;
      const workspaceId = this.laneWorkspaceId?.(options.workspaceId);
      const laneLabel = normalize(options.laneLabel) || 'deploy lane';
      if (!workspaceId) {
        this.showToast?.(`Select a workspace before arming the ${laneLabel}.`);
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
        if (options.requireTerminalApproval && !this.terminalApprovalReady?.()) {
          await this.ensureTerminalDefaultMode?.('approval_required');
        }

        const ready = typeof options.readyCheck === 'function'
          ? !!(await options.readyCheck())
          : !!this.operatorLaneReady?.({ requireTerminalApproval: !!options.requireTerminalApproval });
        if (ready) {
          if (options.prefillPrompt !== false && !normalize(this.chatInput)) {
            await options.draftPrompt?.();
          } else {
            this.focusChatComposer?.();
          }
          this.showToast?.(options.readyToast || 'Deploy lane ready.');
          return true;
        }

        this.showToast?.(options.incompleteToast || 'Deploy lane setup is incomplete. Review mode, runtime, and permissions.');
        return false;
      } catch (e) {
        this.showToast?.(`Could not arm the ${laneLabel}: ${e?.message || e}`);
        return false;
      } finally {
        this.deployLanePreparing = false;
      }
    },

    vercelDeployIntentSeedText(message = '') {
      return this.deployIntentSeedText?.(message) || '';
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
      return !!this.operatorLaneReady?.();
    },

    vercelDeployWorkspaceLabel() {
      return this.laneWorkspaceLabel?.() || 'the selected workspace';
    },

    vercelDeployLaneChecks() {
      return this.operatorLaneChecks?.() || [];
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

    expoDeployIntentSeedText(message = '') {
      return this.deployIntentSeedText?.(message) || '';
    },

    looksLikeExpoDeployIntent(message = '') {
      const lowered = this.expoDeployIntentSeedText?.(message).toLowerCase() || '';
      if (!lowered) return false;
      const mentionsExpo = /\b(expo|eas)\b/.test(lowered);
      const mentionsMobileApp = /\b(mobile companion app|companion-native|mobile app|android app|ios app)\b/.test(lowered);
      const deployAction = /\b(deploy|build|ship|publish|submit|release|internal|production|preview)\b/.test(lowered);
      return deployAction && (mentionsExpo || mentionsMobileApp);
    },

    expoDeployLaneReady() {
      return !!this.operatorLaneReady?.({ requireTerminalApproval: true });
    },

    expoDeployLaneChecks() {
      return this.operatorLaneChecks?.({ requireTerminalApproval: true }) || [];
    },

    expoDeployGuidanceVisible(message = '') {
      return !!this.looksLikeExpoDeployIntent?.(message);
    },

    expoDeployGuidanceSummary() {
      const workspace = this.laneWorkspaceLabel?.() || 'the selected workspace';
      if (this.expoDeployLaneReady?.()) {
        return `${workspace} is armed for real Expo and EAS work. Axon will run from Agent mode on CLI with full access, and terminal sessions will stop for approval before mutating shell commands.`;
      }
      return 'Real Expo and EAS deploy work runs from Agent mode on CLI with Full access and terminal approval. That lets Axon inspect the repo, check Expo auth and DNS, and pause at shell mutation boundaries.';
    },

    expoDeployPrompt() {
      const workspace = this.laneWorkspaceLabel?.() || 'the selected workspace';
      return `Deploy the mobile companion app for ${workspace} to EAS from the real workspace. First inspect apps/companion-native, verify Expo auth, DNS reachability to api.expo.dev, and the EAS build profile. If clear, start the appropriate EAS build with EAS_NO_VCS=1 and report the live build status plus every blocker.`;
    },

    async draftExpoDeployPrompt() {
      const nextPrompt = this.expoDeployPrompt?.() || '';
      if (!normalize(nextPrompt)) return false;
      this.chatInput = nextPrompt;
      this.focusChatComposer?.();
      return true;
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
      return this.prepareOperationalLane?.({
        ...options,
        laneLabel: 'Vercel deploy lane',
        readyCheck: () => this.vercelDeployLaneReady?.(),
        draftPrompt: () => this.draftVercelDeployPrompt?.(options.kind || 'deploy'),
        readyToast: 'Deploy lane ready: Agent + CLI + Full access.',
        incompleteToast: 'Deploy lane setup is incomplete. Review mode, runtime, and permissions.',
      });
    },

    async prepareExpoDeployLane(options = {}) {
      return this.prepareOperationalLane?.({
        ...options,
        laneLabel: 'Expo lane',
        requireTerminalApproval: true,
        readyCheck: () => this.expoDeployLaneReady?.(),
        draftPrompt: () => this.draftExpoDeployPrompt?.(),
        readyToast: 'Expo lane ready: Agent + CLI + Full access + terminal approval.',
        incompleteToast: 'Expo lane setup is incomplete. Review mode, runtime, permissions, and terminal approval.',
      });
    },
  };
}

window.axonChatDeployGuidanceMixin = axonChatDeployGuidanceMixin;
