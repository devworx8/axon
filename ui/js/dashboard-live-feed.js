/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Live Feed
   ══════════════════════════════════════════════════════════════ */

function axonDashboardLiveFeedMixin() {
  return {
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
      if (activeTerminalId && Number(activeTerminalId) === Number(this.terminal.activeSessionId || 0)) {
        this.loadTerminalSessionDetail(activeTerminalId, { silent: true });
      }
      if (!this.dashRecentActivity.length && Array.isArray(payload?.activity) && payload.activity.length) {
        this.dashRecentActivity = payload.activity;
      }
    },
  };
}

window.axonDashboardLiveFeedMixin = axonDashboardLiveFeedMixin;
