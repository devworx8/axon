/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Preview Module
   ══════════════════════════════════════════════════════════════ */

function axonDashboardPreviewMixin() {
  return {

    desktopPreviewShouldStream() {
      const surfaceMode = typeof this.dashboardLiveSurfaceMode === 'function'
        ? this.dashboardLiveSurfaceMode()
        : 'desktop';
      if (this.activeTab === 'dashboard' && surfaceMode !== 'desktop' && !this.composerOptions?.live_desktop_feed) {
        return false;
      }
      return !!(
        (this.activeTab === 'dashboard' && surfaceMode === 'desktop')
        || this.composerOptions?.live_desktop_feed
        || this.chatLoading
        || this.liveOperator?.active
      );
    },

    desktopPreviewIntervalMs() {
      if (this.chatLoading || this.liveOperator?.active) return 3000;
      return 6000;
    },

    async refreshDesktopPreview(force = false) {
      if (!this.desktopPreview.enabled && !force) return;
      this.desktopPreview.loading = true;
      this.desktopPreview.error = '';
      try {
        const cacheBust = Date.now();
        const resp = await fetch(`/api/desktop/preview?w=960&h=540&_=${cacheBust}`, {
          headers: this.authHeaders(),
          cache: 'no-store',
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          throw new Error('Session expired');
        }
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
          const body = await resp.json();
          const msg = body.message || body.detail || 'Desktop preview unavailable';
          throw new Error(body.status === 'no_display'
            ? '🖥️ Screen capture unavailable in this environment'
            : msg);
        }
        if (!resp.ok) {
          const detail = await resp.text().catch(() => '');
          throw new Error(detail || 'Desktop preview unavailable');
        }
        const blob = await resp.blob();
        if (this.desktopPreview.url && this.desktopPreview.url.startsWith('blob:')) {
          URL.revokeObjectURL(this.desktopPreview.url);
        }
        this.desktopPreview.url = URL.createObjectURL(blob);
        this.desktopPreview.lastUpdated = new Date().toISOString();
      } catch (e) {
        this.desktopPreview.error = e.message || 'Desktop preview unavailable';
      }
      this.desktopPreview.loading = false;
    },

    scheduleDesktopPreview() {
      if (this.desktopPreview.timer) clearTimeout(this.desktopPreview.timer);
      if (!this.desktopPreview.enabled || !this.desktopPreviewShouldStream()) return;
      this.desktopPreview.timer = setTimeout(async () => {
        await this.refreshDesktopPreview();
        this.scheduleDesktopPreview();
      }, this.desktopPreviewIntervalMs());
    },

    stopDesktopPreview(force = false) {
      if (this.desktopPreview.timer) clearTimeout(this.desktopPreview.timer);
      this.desktopPreview.timer = null;
      if (!force && this.desktopPreviewShouldStream()) {
        this.scheduleDesktopPreview();
      }
    },

    syncDesktopPreviewStream(forceRefresh = false) {
      if (!this.desktopPreview.enabled) {
        this.stopDesktopPreview(true);
        return;
      }
      if (!this.desktopPreviewShouldStream()) {
        this.stopDesktopPreview(true);
        return;
      }
      if (forceRefresh || !this.desktopPreview.url) {
        this.refreshDesktopPreview(true);
      }
      this.scheduleDesktopPreview();
    },

    toggleLiveDesktopFeed(force = null) {
      const enabled = typeof force === 'boolean' ? force : !this.composerOptions.live_desktop_feed;
      this.composerOptions.live_desktop_feed = enabled;
      if (enabled) {
        this.syncDesktopPreviewStream(true);
      } else {
        this.stopDesktopPreview();
      }
    },
  };
}

window.axonDashboardPreviewMixin = axonDashboardPreviewMixin;
