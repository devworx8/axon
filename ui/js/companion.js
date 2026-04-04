/* ═══════════════════════════════════════════════════
   Axon — Companion + connectors module
   ═══════════════════════════════════════════════════ */

function axonCompanionMixin() {
  const parseJson = (value, fallback = {}) => {
    if (value && typeof value === 'object') return { ...value };
    const raw = String(value || '').trim();
    if (!raw) return { ...fallback };
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? { ...parsed } : { ...fallback };
    } catch (_) {
      return { ...fallback };
    }
  };

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

    async refreshAxonSurfaces() {
      await Promise.allSettled([
        this.loadAttentionInbox?.(),
        this.loadCompanionStatus?.(),
        this.loadConnectorsOverview?.(),
        this.loadVoiceStatus?.(true),
      ]);
    },

    async refreshJarvisSurfaces() {
      return this.refreshAxonSurfaces?.();
    },

    latestCompanionPresence() {
      const scoped = this.companionIdentity?.presence;
      if (scoped && (scoped.device_id || scoped.presence_state || scoped.last_seen_at)) {
        return scoped;
      }
      return this.companionStatus?.latest_presence || null;
    },

    companionLastSeenLabel(value) {
      const raw = String(value || '').trim();
      if (!raw) return '';
      try {
        const isoLike = raw.includes('T') ? raw : raw.replace(' ', 'T') + 'Z';
        if (typeof this.timeAgo === 'function') {
          return this.timeAgo(isoLike);
        }
      } catch (_) {}
      return raw;
    },

    companionDeviceName() {
      const latestPresence = this.latestCompanionPresence();
      const explicit = this.companionIdentity?.device?.name
        || this.companionStatus?.device?.name
        || latestPresence?.device_name
        || '';
      if (explicit) return explicit;
      const devices = Number(this.companionStatus?.counts?.paired_devices || this.companionStatus?.counts?.devices || 0);
      const presence = Number(this.companionStatus?.counts?.active_devices || this.companionStatus?.counts?.presence || 0);
      if (presence > 0) {
        return presence === 1 ? '1 active Axon Online device' : `${presence} active Axon Online devices`;
      }
      if (devices > 0) {
        return devices === 1 ? '1 paired Axon Online device' : `${devices} paired Axon Online devices`;
      }
      return '';
    },

    companionPresenceSummary() {
      const presence = this.latestCompanionPresence() || {};
      const state = String(presence.presence_state || '').trim();
      const voice = String(presence.voice_state || '').trim();
      const app = String(presence.app_state || '').trim();
      const route = String(presence.active_route || '').trim();
      const seen = this.companionLastSeenLabel(presence.last_seen_at);
      const parts = [state, voice, app].filter(Boolean);
      const latestName = String(presence.device_name || '').trim();
      if (latestName || parts.length || route || seen) {
        return [
          latestName ? `${latestName}${route ? ` on ${route}` : ''}` : (route ? `Route ${route}` : ''),
          parts.join(' · '),
          seen ? `seen ${seen}` : '',
        ].filter(Boolean).join(' · ');
      }
      const devices = Number(this.companionStatus?.counts?.paired_devices || this.companionStatus?.counts?.devices || 0);
      const sessions = Number(this.companionStatus?.counts?.active_sessions || this.companionStatus?.counts?.sessions || 0);
      const activePresence = Number(this.companionStatus?.counts?.active_devices || this.companionStatus?.counts?.presence || 0);
      if (activePresence > 0) {
        return `${activePresence} active device${activePresence === 1 ? '' : 's'} · ${sessions} live session${sessions === 1 ? '' : 's'} right now.`;
      }
      if (devices > 0) {
        return `${devices} paired device${devices === 1 ? '' : 's'} registered${sessions > 0 ? ` · ${sessions} live session${sessions === 1 ? '' : 's'}` : ''}.`;
      }
      return 'No paired companion is active yet.';
    },

    companionStatusTone() {
      if (this.companionStatus?.session_valid) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (Number(this.companionStatus?.counts?.active_devices || this.companionStatus?.counts?.presence || 0) > 0) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (Number(this.companionStatus?.counts?.paired_devices || this.companionStatus?.counts?.devices || 0) > 0) return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200';
      if (this.companionStatus?.token_present) return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
      return 'border-slate-700 bg-slate-950/70 text-slate-300';
    },

    companionConnectionLabel() {
      if (this.companionStatus?.session_valid) return 'Connected';
      const presence = Number(this.companionStatus?.counts?.active_devices || this.companionStatus?.counts?.presence || 0);
      const devices = Number(this.companionStatus?.counts?.paired_devices || this.companionStatus?.counts?.devices || 0);
      if (presence > 0) return 'Live';
      if (devices > 0) return 'Paired';
      if (this.companionStatus?.token_present) return 'Token';
      return 'Idle';
    },

    companionAxonState() {
      const presence = this.latestCompanionPresence?.() || {};
      const meta = parseJson(presence.meta_json);
      return parseJson(meta.axon_mode);
    },

    companionAxonWakePhrase() {
      return String(this.companionAxonState?.().wake_phrase || 'Axon').trim() || 'Axon';
    },

    companionAxonStatusLabel() {
      const state = String(this.companionAxonState?.().monitoring_state || '').trim();
      return state ? state.replace(/_/g, ' ') : 'idle';
    },

    companionAxonVoiceLabel() {
      const state = this.companionAxonState?.() || {};
      return String(
        state.voice_identity_label
        || state.voice_identity
        || state.voice_provider
        || (this.voice?.server?.synthesis_available ? 'local synthesis' : 'speech pending'),
      ).trim();
    },

    companionAxonSummary() {
      const state = this.companionAxonState?.() || {};
      const summary = String(state.summary || '').trim();
      if (summary) return summary;
      const degraded = String(state.degraded_reason || state.last_error || '').trim();
      if (degraded) return degraded;
      if (state.armed) {
        return `Listening for '${this.companionAxonWakePhrase?.()}'.`;
      }
      return 'Arm Axon mode on the paired device to keep the foreground sentinel loop ready.';
    },

    companionAxonLastCommand() {
      return String(this.companionAxonState?.().last_command_text || '').trim();
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
