/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Live Feed
   ══════════════════════════════════════════════════════════════ */

function axonDashboardLiveFeedMixin() {
  const parseDateMs = (value = '') => {
    const parsed = Date.parse(String(value || ''));
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const sessionMatches = (session, sessionId) => Number(session?.id || 0) === Number(sessionId || 0);

  return {
    dashboardLiveBrowserUrl() {
      const candidates = [
        this.currentWorkspacePreview?.()?.url,
        this.browserSession?.()?.attached_preview_url,
        this.scopedDevPreview?.()?.url,
      ];
      for (const candidate of candidates) {
        const url = String(candidate || '').trim();
        if (!url) continue;
        try {
          const parsed = new URL(url, window.location.href);
          if (parsed.origin === window.location.origin) continue;
          return parsed.toString();
        } catch (_) {}
      }
      return '';
    },

    dashboardLiveTerminalSessionId() {
      const activeSessionId = Number(this.liveFeed?.latest?.terminal?.active_session_id || 0);
      if (activeSessionId) return activeSessionId;
      const running = (this.terminal.sessions || []).find(item => item.running);
      return Number(running?.id || 0);
    },

    dashboardLiveTerminalSession() {
      const sessionId = this.dashboardLiveTerminalSessionId();
      if (!sessionId) return null;
      return (this.terminal.sessions || []).find(item => sessionMatches(item, sessionId))
        || (sessionMatches(this.terminal.liveSessionDetail, sessionId) ? this.terminal.liveSessionDetail : null)
        || (sessionMatches(this.terminal.sessionDetail, sessionId) ? this.terminal.sessionDetail : null)
        || null;
    },

    dashboardLiveTerminalDetail() {
      const sessionId = this.dashboardLiveTerminalSessionId();
      if (!sessionId) return null;
      if (sessionMatches(this.terminal.liveSessionDetail, sessionId)) return this.terminal.liveSessionDetail;
      if (sessionMatches(this.terminal.sessionDetail, sessionId)) return this.terminal.sessionDetail;
      return null;
    },

    dashboardLiveTerminalEvents(limit = 8) {
      const detail = this.dashboardLiveTerminalDetail();
      if (!Array.isArray(detail?.recent_events)) return [];
      return [...detail.recent_events]
        .slice(-Math.max(1, limit))
        .reverse();
    },

    dashboardLiveSurfaceMode() {
      const activeMode = String(this.liveOperator?.mode || this.liveFeed?.latest?.operator?.mode || '').trim().toLowerCase();
      const terminalSessionId = this.dashboardLiveTerminalSessionId();
      if (activeMode === 'terminal' && terminalSessionId) return 'terminal';
      if (this.dashboardLiveBrowserUrl()) return 'browser';
      if (terminalSessionId) return 'terminal';
      return 'desktop';
    },

    dashboardLiveSurfaceModeLabel() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser') return 'Browser';
      if (mode === 'terminal') return 'Terminal';
      return 'Desktop';
    },

    dashboardLiveSurfaceDescription() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser') {
        return this.browserControlDetail?.()
          || 'Axon attached a live browser surface instead of mirroring the whole desktop.';
      }
      if (mode === 'terminal') {
        const session = this.dashboardLiveTerminalSession();
        const command = String(session?.active_command || '').trim();
        if (command) return `Streaming live shell output for ${command}.`;
        return 'Streaming the active terminal session instead of a static full-screen screenshot.';
      }
      return 'Fallback capture of the local desktop when no dedicated browser or terminal surface is active.';
    },

    dashboardLiveSurfaceStatusTone() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser' && typeof this.browserPreviewStatusTone === 'function') {
        return this.browserPreviewStatusTone();
      }
      if (mode === 'terminal') {
        const session = this.dashboardLiveTerminalSession();
        const status = String(session?.status || '').trim().toLowerCase();
        if (session?.running) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
        if (status === 'failed' || status === 'stopped') return 'border-rose-500/20 bg-rose-500/10 text-rose-300';
        if (status === 'completed') return 'border-sky-500/20 bg-sky-500/10 text-sky-200';
        return 'border-slate-700 bg-slate-950/60 text-slate-400';
      }
      if (this.desktopPreview.error) return 'border-rose-500/20 bg-rose-500/10 text-rose-300';
      if (this.desktopPreview.loading) return 'border-amber-500/20 bg-amber-500/10 text-amber-300';
      if (this.desktopPreview.url) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
      return 'border-slate-700 bg-slate-950/60 text-slate-400';
    },

    dashboardLiveSurfaceStatusLabel() {
      const modeLabel = this.dashboardLiveSurfaceModeLabel();
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser' && typeof this.browserPreviewStatusLabel === 'function') {
        return `${modeLabel} · ${this.browserPreviewStatusLabel()}`;
      }
      if (mode === 'terminal') {
        const session = this.dashboardLiveTerminalSession();
        const status = session?.running
          ? 'Streaming'
          : (String(session?.status || 'ready').trim() || 'ready').replace(/[_-]+/g, ' ');
        const label = status.charAt(0).toUpperCase() + status.slice(1);
        return `${modeLabel} · ${label}`;
      }
      if (this.desktopPreview.error) return `${modeLabel} · Error`;
      if (this.desktopPreview.loading) return `${modeLabel} · Refreshing`;
      if (this.desktopPreview.url) return `${modeLabel} · Live`;
      return `${modeLabel} · Ready`;
    },

    dashboardLiveSurfaceUpdatedAt() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser') {
        return String(
          this.currentWorkspacePreview?.()?.updated_at
          || this.browserSession?.()?.last_seen_at
          || this.liveFeed?.latest?.at
          || ''
        ).trim();
      }
      if (mode === 'terminal') {
        const detail = this.dashboardLiveTerminalDetail();
        const session = this.dashboardLiveTerminalSession();
        return String(
          detail?.last_output_at
          || detail?.updated_at
          || session?.last_output_at
          || this.liveFeed?.latest?.at
          || ''
        ).trim();
      }
      return String(this.desktopPreview.lastUpdated || this.liveFeed?.latest?.at || '').trim();
    },

    dashboardLiveSurfaceScopeLabel() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser') {
        return String(
          this.browserAttachedWorkspaceLabel?.()
          || this.browserSession?.()?.attached_workspace_name
          || this.chatProject?.name
          || 'Browser surface'
        ).trim();
      }
      if (mode === 'terminal') {
        const session = this.dashboardLiveTerminalSession();
        return String(session?.workspace_name || session?.title || session?.cwd || 'Terminal').trim();
      }
      return String(this.chatProject?.name || 'Desktop capture').trim();
    },

    dashboardLiveSurfaceActionLabel() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser') return 'Open';
      if (mode === 'terminal') return 'Inspect';
      return 'Refresh';
    },

    async dashboardLiveSurfaceAction() {
      const mode = this.dashboardLiveSurfaceMode();
      if (mode === 'browser') {
        const url = this.dashboardLiveBrowserUrl();
        if (url) window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }
      if (mode === 'terminal') {
        const sessionId = this.dashboardLiveTerminalSessionId();
        this.switchTab?.('chat');
        await this.toggleTerminalMode?.(true);
        if (sessionId) {
          await this.loadTerminalSessionDetail?.(sessionId, { silent: true });
        }
        return;
      }
      await this.refreshDesktopPreview?.(true);
    },

    async hydrateDashboardLiveTerminal(payload = null) {
      const targetId = Number(payload?.terminal?.active_session_id || this.dashboardLiveTerminalSessionId() || 0);
      if (!targetId || !this.authenticated) return;
      const currentDetail = this.dashboardLiveTerminalDetail();
      const lastLoadedAt = parseDateMs(
        this.terminal.liveSessionDetailLoadedAt
        || this.terminal.lastDetailLoadedAt
        || ''
      );
      const ageMs = lastLoadedAt ? (Date.now() - lastLoadedAt) : Number.POSITIVE_INFINITY;
      const pending = this.terminal.liveSessionHydration || null;
      if (Number(pending?.sessionId || 0) === targetId && (Date.now() - Number(pending?.startedAt || 0)) < 1800) {
        return;
      }
      if (sessionMatches(currentDetail, targetId) && ageMs < 1600) return;
      this.terminal.liveSessionHydration = { sessionId: targetId, startedAt: Date.now() };
      try {
        const detail = await this.api('GET', `/api/terminal/sessions/${targetId}`);
        if (!sessionMatches(detail, targetId)) return;
        this.terminal.liveSessionDetail = detail;
        this.terminal.liveSessionDetailLoadedAt = new Date().toISOString();
        const sessions = [...(this.terminal.sessions || [])];
        const index = sessions.findIndex(item => sessionMatches(item, targetId));
        if (index >= 0) sessions[index] = { ...sessions[index], ...detail };
        else sessions.unshift(detail);
        this.terminal.sessions = sessions;
      } catch (_) {
        // Live terminal hydration is opportunistic.
      } finally {
        if (Number(this.terminal.liveSessionHydration?.sessionId || 0) === targetId) {
          this.terminal.liveSessionHydration = null;
        }
      }
    },

    async connectLiveFeed() {
      this.ensureVoiceAttentionMonitor?.();
      if (!this.settingsForm.live_feed_enabled) {
        this.liveFeed.connected = false;
        this.liveFeed.connecting = false;
        this.liveFeed.reconnecting = false;
        this.liveFeed.error = '';
        return;
      }
      if (!this.authenticated || this.liveFeed.connecting) return;
      if (this.liveFeed.controller) {
        try { this.liveFeed.controller.abort(); } catch (_) {}
      }
      this.liveFeed.connecting = true;
      const controller = new AbortController();
      this.liveFeed.controller = controller;
      try {
        const resp = await fetch('/api/live/feed', {
          headers: this.authHeaders(),
          cache: 'no-store',
          signal: controller.signal,
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          return;
        }
        if (!resp.ok || !resp.body) {
          throw new Error(resp.statusText || 'Live feed unavailable');
        }
        this.liveFeed.connected = true;
        this.liveFeed.connecting = false;
        this.liveFeed.reconnecting = false;
        this.liveFeed.error = '';
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const payload = JSON.parse(line.slice(6));
              this.handleLiveFeedSnapshot(payload);
            } catch (_) {}
          }
        }
        throw new Error('Live feed disconnected');
      } catch (e) {
        if (controller.signal.aborted) return;
        this.liveFeed.connected = false;
        this.liveFeed.connecting = false;
        this.liveFeed.reconnecting = true;
        this.liveFeed.error = e.message || 'Live feed unavailable';
        setTimeout(() => this.connectLiveFeed(), 3000);
      }
    },

    handleLiveFeedSnapshot(payload) {
      this.liveFeed.latest = payload;
      this.liveFeed.connected = true;
      this.liveFeed.reconnecting = false;
      this.syncVoiceAttentionFromLiveFeed?.(payload);
      if (payload?.connection) this.connectionState = payload.connection;
      if (payload?.runtime) {
        this.runtimeStatus = {
          ...this.runtimeStatus,
          ...payload.runtime,
        };
      }
      if (payload?.operator && typeof this.syncWorkspaceLiveOperatorSnapshot === 'function') {
        this.syncWorkspaceLiveOperatorSnapshot(payload.operator);
      }
      if (Array.isArray(payload?.auto_sessions) && typeof this.syncAutoSessionsFromSnapshot === 'function') {
        this.syncAutoSessionsFromSnapshot(payload.auto_sessions);
      }
      if (payload?.browser_actions) {
        this.browserActions = {
          ...this.browserActions,
          ...payload.browser_actions,
        };
      }
      if (Array.isArray(payload?.terminal?.sessions)) {
        this.terminal.sessions = payload.terminal.sessions;
      }
      const activeTerminalId = payload?.terminal?.active_session_id;
      if (activeTerminalId) {
        this.hydrateDashboardLiveTerminal?.(payload);
      }
      if (activeTerminalId && Number(activeTerminalId) === Number(this.terminal.activeSessionId || 0)) {
        this.loadTerminalSessionDetail(activeTerminalId, { silent: true });
      }
      if (Array.isArray(payload?.activity)) {
        this.dashRecentActivity = payload.activity;
      }
      this.syncDesktopPreviewStream?.(false);
    },
  };
}

window.axonDashboardLiveFeedMixin = axonDashboardLiveFeedMixin;
