/* ══════════════════════════════════════════════════════════════
   Axon — Chat Workspace Status
   ══════════════════════════════════════════════════════════════ */

function axonChatWorkspaceStatusMixin() {
  const REFRESH_THROTTLE_MS = 3000;

  return {
    currentWorkspaceBranchName() {
      const autoBranch = this.autonomousConsoleActive?.()
        ? String(this.currentWorkspaceAutoSession?.()?.branch_name || '').trim()
        : '';
      const envBranch = String(this._workspaceEnv?.git_branch || '').trim();
      const projectBranch = String(this.chatProject?.git_branch || '').trim();
      return autoBranch || envBranch || projectBranch || '';
    },

    shouldShowWorkspaceBranch() {
      return !!String(this.chatProjectId || '').trim() && !!this.currentWorkspaceBranchName();
    },

    workspaceBranchTitle() {
      const branch = this.currentWorkspaceBranchName();
      if (!branch) return '';
      const workspace = this.chatProject?.name || 'workspace';
      const scope = this.autonomousConsoleActive?.() && String(this.currentWorkspaceAutoSession?.()?.branch_name || '').trim()
        ? 'Auto worktree branch'
        : 'Repo branch';
      return `${scope} for ${workspace}: ${branch}`;
    },

    workspaceStatusNeedsRefresh() {
      if (!String(this.chatProjectId || '').trim()) return false;
      if (!this._workspaceEnv?.git_branch) return true;
      if (this.currentWorkspaceRunActive?.()) return true;
      if (this.autonomousConsoleActive?.()) return true;
      if (this.agentMode) return true;
      return String(this.liveOperator?.workspaceId || '').trim() === String(this.chatProjectId || '').trim();
    },

    maybeRefreshWorkspaceEnvFromStatus(force = false) {
      if (typeof this._refreshWorkspaceEnv !== 'function') return;
      if (!String(this.chatProjectId || '').trim()) return;
      if (!force && !this.workspaceStatusNeedsRefresh()) return;
      if (this._workspaceEnvRefreshInFlight) return;

      const now = Date.now();
      const lastAt = Number(this._workspaceEnvRefreshedAt || 0);
      if (!force && now - lastAt < REFRESH_THROTTLE_MS) return;

      this._workspaceEnvRefreshedAt = now;
      this._workspaceEnvRefreshInFlight = true;
      Promise.resolve(this._refreshWorkspaceEnv())
        .catch(() => {})
        .finally(() => {
          this._workspaceEnvRefreshInFlight = false;
          this._workspaceEnvRefreshedAt = Date.now();
        });
    },
  };
}

window.axonChatWorkspaceStatusMixin = axonChatWorkspaceStatusMixin;
