/* ═══════════════════════════════════════════════════
   Axon — Companion + connectors module
   ═══════════════════════════════════════════════════ */

function axonCompanionMixin() {
  return {
    companionStatus: {
      auth_enabled: false,
      session_valid: false,
      device: null,
      auth_session: null,
      counts: { devices: 0, sessions: 0, presence: 0 },
      token_present: false,
    },
    companionIdentity: {
      device: null,
      auth_session: null,
      presence: null,
      sessions: [],
    },
    companionLoading: false,
    companionError: '',
    connectorsOverview: { workspaces: [] },
    connectorsLoading: false,
    connectorsError: '',

    async loadCompanionStatus() {
      if (this.companionLoading) return;
      this.companionLoading = true;
      try {
        const [status, identity] = await Promise.all([
          this.api('GET', '/api/companion/status'),
          this.api('GET', '/api/companion/identity'),
        ]);
        this.companionStatus = status || this.companionStatus;
        this.companionIdentity = identity || this.companionIdentity;
        this.companionError = '';
      } catch (e) {
        console.error('[companion] Failed to load status:', e);
        this.companionError = e?.message || 'Failed to load companion status';
      } finally {
        this.companionLoading = false;
      }
    },

    async loadConnectorsOverview(limit = 8) {
      if (this.connectorsLoading) return;
      this.connectorsLoading = true;
      try {
        this.connectorsOverview = await this.api('GET', `/api/connectors/overview?limit=${encodeURIComponent(String(limit || 8))}`);
        this.connectorsError = '';
      } catch (e) {
        console.error('[companion] Failed to load connectors overview:', e);
        this.connectorsError = e?.message || 'Failed to load connectors overview';
      } finally {
        this.connectorsLoading = false;
      }
    },

    async refreshJarvisSurfaces() {
      await Promise.allSettled([
        this.loadAttentionInbox?.(),
        this.loadCompanionStatus?.(),
        this.loadConnectorsOverview?.(),
      ]);
    },

    companionDeviceName() {
      return this.companionIdentity?.device?.name || this.companionStatus?.device?.name || '';
    },

    companionPresenceSummary() {
      const presence = this.companionIdentity?.presence || {};
      const state = String(presence.presence_state || '').trim();
      const voice = String(presence.voice_state || '').trim();
      const app = String(presence.app_state || '').trim();
      const parts = [state, voice, app].filter(Boolean);
      return parts.length ? parts.join(' · ') : 'No paired companion is active yet.';
    },

    companionStatusTone() {
      if (this.companionStatus?.session_valid) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (this.companionStatus?.token_present) return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
      return 'border-slate-700 bg-slate-950/70 text-slate-300';
    },

    connectorWorkspaceItems() {
      return Array.isArray(this.connectorsOverview?.workspaces)
        ? this.connectorsOverview.workspaces.slice(0, 6)
        : [];
    },

    connectorRelationshipItems(workspaceSummary = {}) {
      return Array.isArray(workspaceSummary?.relationships) ? workspaceSummary.relationships.slice(0, 4) : [];
    },

    connectorSystemTone(system = '') {
      const key = String(system || '').trim().toLowerCase();
      if (key === 'github') return 'border-slate-600 bg-slate-950/80 text-slate-200';
      if (key === 'vercel') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (key === 'sentry') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200';
    },

    connectorRelationshipLabel(relationship = {}) {
      const system = String(relationship?.external_system || 'system').trim();
      const name = String(relationship?.external_name || relationship?.external_id || '').trim();
      return name ? `${system} · ${name}` : system;
    },

    openConnectorWorkspace(summary = {}) {
      const workspaceId = String(summary?.workspace?.id || '').trim();
      if (!workspaceId) return;
      this.chatProjectId = workspaceId;
      this.updateChatProject?.();
      this.switchTab?.('chat');
    },
  };
}

window.axonCompanionMixin = axonCompanionMixin;
