/* ═══════════════════════════════════════════════════
   Axon — DevOps monitoring panel
   ═══════════════════════════════════════════════════ */

function axonDevopsMixin() {
  return {
    devopsErrors: [],
    devopsUsage: {},
    devopsBackends: [],
    devopsQuota: { cost_pct: 0, token_pct: 0 },
    devopsCliInstaller: {
      package_name: '@openai/codex',
      binary_name: 'codex',
    },
    devopsCliInstallLoading: false,
    devopsCliInstallResult: null,

    async devopsRefresh() {
      await Promise.all([
        this.devopsLoadErrors(),
        this.devopsLoadUsage(),
        this.devopsLoadBackends(),
        this.devopsLoadQuota(),
        this.loadExpoOverview?.(true),
      ]);
    },

    async devopsLoadErrors() {
      try {
        const data = await this.api('GET', '/api/devops/errors');
        this.devopsErrors = data.errors || [];
      } catch (e) {
        console.error('[devops] Error loading errors:', e);
      }
    },

    async devopsLoadUsage() {
      try {
        this.devopsUsage = await this.api('GET', '/api/devops/usage/summary?days=30');
      } catch (e) {
        console.error('[devops] Error loading usage:', e);
      }
    },

    async devopsLoadBackends() {
      try {
        const data = await this.api('GET', '/api/devops/usage/backends?days=30');
        this.devopsBackends = data.backends || [];
      } catch (e) {
        console.error('[devops] Error loading backends:', e);
      }
    },

    async devopsLoadQuota() {
      try {
        this.devopsQuota = await this.api('GET', '/api/devops/usage/quota');
      } catch (e) {
        console.error('[devops] Error loading quota:', e);
      }
    },

    async devopsSetStatus(errorId, status) {
      try {
        await this.api('PATCH', `/api/devops/errors/${errorId}/status`, { status });
        await this.devopsLoadErrors();
        this.showToast(`Error ${status}`);
      } catch (e) {
        this.showToast('Failed to update error status');
      }
    },

    async devopsPollSentry() {
      try {
        const data = await this.api('POST', '/api/devops/sentry/poll');
        this.showToast(`Sentry: ${data.ingested || 0} issues ingested`);
        await this.devopsLoadErrors();
      } catch (e) {
        this.showToast('Sentry poll failed');
      }
    },

    async devopsInstallCliExtension() {
      const packageName = String(this.devopsCliInstaller?.package_name || '').trim();
      const binaryName = String(this.devopsCliInstaller?.binary_name || '').trim();
      if (!packageName) {
        this.showToast('Enter an npm package name first');
        return;
      }
      this.devopsCliInstallLoading = true;
      this.devopsCliInstallResult = null;
      try {
        const result = await this.api('POST', '/api/devops/cli-extensions/npm/install', {
          package_name: packageName,
          binary_name: binaryName,
        });
        this.devopsCliInstallResult = result;
        if (result?.command_preview && this._copyCommandPreview) {
          await this._copyCommandPreview(result.command_preview);
        }
        if (this.loadRuntimeStatus) await this.loadRuntimeStatus();
        this.showToast(result?.message || 'CLI install finished');
      } catch (e) {
        this.devopsCliInstallResult = {
          status: 'error',
          message: e.message || 'CLI install failed',
        };
        this.showToast(this.devopsCliInstallResult.message);
      }
      this.devopsCliInstallLoading = false;
    },

    devopsFormatNumber(n) {
      if (!n) return '0';
      if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
      if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
      return String(n);
    },
  };
}

window.axonDevopsMixin = axonDevopsMixin;
