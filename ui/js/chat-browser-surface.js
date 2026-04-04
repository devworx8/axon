/* ══════════════════════════════════════════════════════════════
   Axon — Chat Browser Surface
   ══════════════════════════════════════════════════════════════ */

function axonChatBrowserSurfaceMixin() {
  const blankPreviewState = (scope = {}) => ({
    session: null,
    loading: false,
    error: '',
    workspace_id: scope?.workspace_id || null,
    workspace_name: scope?.workspace_name || '',
    auto_session_id: String(scope?.auto_session_id || '').trim(),
  });

  return {
    currentPreviewScope() {
      const projectId = parseInt(String(this.chatProjectId || 0), 10) || 0;
      const auto = this.currentWorkspaceAutoSession?.() || null;
      return {
        workspace_id: projectId || null,
        workspace_name: this.chatProject?.name || '',
        auto_session_id: String(auto?.session_id || '').trim(),
        title: String(auto?.title || this.chatProject?.name || 'workspace').trim(),
      };
    },

    currentPreviewScopeKey() {
      const scope = this.currentPreviewScope?.() || {};
      return `${String(scope.workspace_id || '').trim()}:${String(scope.auto_session_id || '').trim()}`;
    },

    scopedWorkspacePreviewState() {
      const scope = this.currentPreviewScope?.() || {};
      const fallback = blankPreviewState(scope);
      const state = this.workspacePreview || {};
      const stateKey = `${String(state.workspace_id || '').trim()}:${String(state.auto_session_id || '').trim()}`;
      const scopeKey = this.currentPreviewScopeKey?.() || '';
      if (!String(scope.workspace_id || '').trim()) return fallback;
      if (stateKey !== scopeKey) return fallback;
      return { ...fallback, ...state };
    },

    currentWorkspacePreview() {
      const scope = this.currentPreviewScope?.() || {};
      const scopeWorkspaceId = String(scope.workspace_id || '').trim();
      if (!scopeWorkspaceId) return null;
      const state = this.scopedWorkspacePreviewState?.() || {};
      const session = state.session || null;
      if (!session) return null;
      const previewWorkspaceId = String(session.workspace_id || state.workspace_id || '').trim();
      const previewAutoSessionId = String(session.auto_session_id || state.auto_session_id || '').trim();
      const scopeAutoSessionId = String(scope.auto_session_id || '').trim();
      if (previewWorkspaceId && previewWorkspaceId !== scopeWorkspaceId) return null;
      if (previewAutoSessionId !== scopeAutoSessionId) return null;
      return session;
    },

    currentWorkspacePreviewLoading() {
      return !!this.scopedWorkspacePreviewState?.().loading;
    },

    currentWorkspacePreviewError() {
      return String(this.scopedWorkspacePreviewState?.().error || '').trim();
    },

    scopedDevPreview(scopeKey = null) {
      const scope = this.currentPreviewScope?.() || {};
      const key = String(scopeKey == null ? this.currentPreviewScopeKey?.() : scopeKey).trim();
      const preview = this.devPreview || {};
      const previewKey = String(preview.scope_key || '').trim();
      if (key) {
        if (previewKey !== key) {
          return {
            url: '',
            visible: false,
            scope_key: key,
            workspace_id: scope.workspace_id || null,
            auto_session_id: String(scope.auto_session_id || '').trim(),
          };
        }
      } else if (previewKey) {
        return {
          url: '',
          visible: false,
          scope_key: '',
          workspace_id: null,
          auto_session_id: '',
        };
      }
      return {
        url: String(preview.url || '').trim(),
        visible: !!preview.visible,
        scope_key: previewKey,
        workspace_id: preview.workspace_id || null,
        auto_session_id: String(preview.auto_session_id || '').trim(),
      };
    },

    rememberScopedDevPreview(url = '', options = {}) {
      const trimmed = String(url || '').trim();
      const scope = options?.scope || this.currentPreviewScope?.() || {};
      const scopeKey = String(options?.scopeKey || this.currentPreviewScopeKey?.() || '').trim();
      this.devPreview = {
        ...(this.devPreview || {}),
        url: trimmed,
        visible: !!trimmed,
        scope_key: scopeKey,
        workspace_id: scope.workspace_id || null,
        auto_session_id: String(scope.auto_session_id || '').trim(),
      };
      return this.devPreview;
    },

    clearScopedDevPreview(options = {}) {
      const scopeKey = String(options?.scopeKey == null ? this.currentPreviewScopeKey?.() : options.scopeKey).trim();
      const previewKey = String(this.devPreview?.scope_key || '').trim();
      if (scopeKey && previewKey && previewKey !== scopeKey) return this.devPreview;
      this.devPreview = {
        ...(this.devPreview || {}),
        url: '',
        visible: false,
        scope_key: '',
        workspace_id: null,
        auto_session_id: '',
      };
      return this.devPreview;
    },

    setScopedPreviewUrl(url = '') {
      const trimmed = String(url || '').trim();
      if (!trimmed) return '';
      this.rememberScopedDevPreview(trimmed);
      this.panelBrowserOpen = true;
      return trimmed;
    },

    previewReadyForCurrentWorkspace() {
      return !!String(this.currentWorkspacePreview?.()?.url || this.scopedDevPreview?.()?.url || '').trim();
    },

    browserSession() {
      const raw = this.browserActions?.session || {};
      const scope = this.currentPreviewScope?.() || {};
      const scopeWorkspaceId = String(scope.workspace_id || '').trim();
      if (!scopeWorkspaceId) return raw;
      const scopeKey = this.currentPreviewScopeKey?.() || '';
      const attachedScopeKey = String(raw?.attached_scope_key || '').trim();
      const attachedWorkspaceId = String(raw?.attached_workspace_id || '').trim();
      const attachedAutoSessionId = String(raw?.attached_auto_session_id || '').trim();
      const scopeAutoSessionId = String(scope.auto_session_id || '').trim();
      if (attachedScopeKey) return attachedScopeKey === scopeKey ? raw : {};
      if (!attachedWorkspaceId) return {};
      if (attachedWorkspaceId !== scopeWorkspaceId) return {};
      if (attachedAutoSessionId !== scopeAutoSessionId) return {};
      return raw;
    },

    browserFrameUrl() {
      const scope = this.currentPreviewScope?.() || {};
      return String(
        this.currentWorkspacePreview?.()?.url
        || this.browserSession()?.attached_preview_url
        || this.scopedDevPreview?.()?.url
        || (!String(scope.workspace_id || '').trim() ? this.browserSession()?.url : '')
        || ''
      ).trim();
    },

    browserAttachedWorkspaceLabel() {
      const session = this.browserSession();
      const previewState = this.scopedWorkspacePreviewState?.() || {};
      return session?.attached_workspace_name || previewState.workspace_name || this.chatProject?.name || 'Workspace';
    },

    browserControlStatusLabel() {
      const preview = this.currentWorkspacePreview?.() || {};
      const status = String(preview?.status || this.browserSession()?.attached_preview_status || '').trim().toLowerCase();
      if (this.currentWorkspacePreviewLoading?.()) return 'Starting';
      if (status === 'running') return 'Live';
      if (status) return status.replace(/_/g, ' ');
      if (this.browserSession()?.connected) return 'Attached';
      return 'Idle';
    },

    browserControlDetail() {
      const preview = this.currentWorkspacePreview?.() || {};
      if (this.currentWorkspacePreviewLoading?.()) {
        return `Axon is starting a live page for ${this.browserAttachedWorkspaceLabel()}.`;
      }
      if (this.currentWorkspacePreviewError?.()) return this.currentWorkspacePreviewError();
      if (preview?.last_error) return preview.last_error;
      if (this.browserSession()?.control_owner === 'axon' && this.browserFrameUrl()) {
        return `${this.browserAttachedWorkspaceLabel()} is attached to Axon's browser surface.`;
      }
      return 'Start the live page to give Axon a controlled browser surface for preview and browser actions.';
    },

    browserPreviewStatusKey() {
      const preview = this.currentWorkspacePreview?.() || {};
      const rawStatus = String(preview?.status || this.browserSession()?.attached_preview_status || '').trim().toLowerCase();
      if (this.currentWorkspacePreviewLoading?.()) return 'starting';
      if (this.currentWorkspacePreviewError?.() || preview?.last_error || rawStatus === 'error') return 'error';
      if (rawStatus === 'running') return preview?.healthy === false ? 'attention' : 'live';
      if (rawStatus === 'starting') return 'starting';
      if (rawStatus === 'stopped') return 'stopped';
      if (this.browserSession()?.control_owner === 'axon' && this.browserFrameUrl()) return 'attached';
      if (this.browserSession()?.connected) return 'connected';
      return 'idle';
    },

    browserPreviewStatusLabel() {
      const key = this.browserPreviewStatusKey();
      if (key === 'live') return 'Live';
      if (key === 'attention') return 'Needs attention';
      if (key === 'starting') return 'Starting';
      if (key === 'error') return 'Error';
      if (key === 'attached') return 'Attached';
      if (key === 'connected') return 'Connected';
      if (key === 'stopped') return 'Stopped';
      return 'Idle';
    },

    browserPreviewStatusTone() {
      const key = this.browserPreviewStatusKey();
      if (key === 'live') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (key === 'attention' || key === 'starting') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
      if (key === 'error') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      if (key === 'attached' || key === 'connected') return 'border-sky-500/20 bg-sky-500/10 text-sky-200';
      if (key === 'stopped') return 'border-slate-700 bg-slate-950/70 text-slate-400';
      return 'border-slate-700 bg-slate-950/70 text-slate-400';
    },

    browserSourcePath() {
      return String(
        this.currentWorkspacePreview?.()?.source_workspace_path
        || this.browserSession()?.attached_source_workspace_path
        || (String(this.chatProjectId || '').trim() ? this.chatProject?.path : '')
        || ''
      ).trim();
    },

    browserCommandLabel() {
      if (this.currentWorkspacePreviewLoading?.()) {
        return `Starting ${this.browserAttachedWorkspaceLabel()} live page…`;
      }
      return String(
        this.currentWorkspacePreview?.()?.command
        || this.browserSession()?.title
        || 'Attach a live page so Axon can inspect, verify, and propose browser actions here.'
      ).trim();
    },

    composerCompactMode() {
      if (this.isMobile) return false;
      const previewOpen = !!(
        this.panelBrowserOpen &&
        (
          this.browserFrameUrl()
          || this.currentWorkspacePreviewLoading?.()
        )
      );
      const panelWidth = Number(this.consolePanelWidth || 0);
      return previewOpen || panelWidth >= Math.round(window.innerWidth * 0.4);
    },

    async loadWorkspacePreview() {
      const scope = this.currentPreviewScope();
      const scopeKey = this.currentPreviewScopeKey();
      const requestSeq = Number(this._workspacePreviewRequestSeq || 0) + 1;
      this._workspacePreviewRequestSeq = requestSeq;
      this._workspacePreviewScopeKey = scopeKey;
      if (!scope.workspace_id) {
        this.workspacePreview = blankPreviewState(scope);
        this.clearScopedDevPreview({ scopeKey });
        return null;
      }
      const scopedPreview = this.currentWorkspacePreview?.() || null;
      this.workspacePreview = {
        session: scopedPreview,
        loading: true,
        error: '',
        workspace_id: scope.workspace_id,
        workspace_name: scope.workspace_name,
        auto_session_id: scope.auto_session_id,
      };
      if (!scopedPreview) {
        this.clearScopedDevPreview({ scopeKey });
      }
      try {
        const qs = new URLSearchParams();
        if (scope.auto_session_id) qs.set('auto_session_id', scope.auto_session_id);
        const data = await this.api('GET', `/api/workspaces/${encodeURIComponent(scope.workspace_id)}/preview${qs.toString() ? `?${qs.toString()}` : ''}`);
        if (requestSeq !== this._workspacePreviewRequestSeq || this._workspacePreviewScopeKey !== scopeKey) return null;
        this.workspacePreview = {
          session: data?.preview || null,
          loading: false,
          error: '',
          workspace_id: scope.workspace_id,
          workspace_name: scope.workspace_name,
          auto_session_id: scope.auto_session_id,
        };
        if (data?.preview?.url) {
          this.rememberScopedDevPreview(data.preview.url, { scope, scopeKey });
          this.panelBrowserOpen = true;
          this.ensureWorkspacePreviewLayout(true);
        } else {
          this.clearScopedDevPreview({ scopeKey });
        }
        if (!data?.preview?.url && scope.auto_session_id) {
          const auto = this.currentWorkspaceAutoSession?.() || null;
          if (auto?.preview_url) {
            this.workspacePreview = {
              ...(this.workspacePreview || {}),
              session: {
                ...(this.workspacePreview?.session || {}),
                auto_session_id: scope.auto_session_id,
                url: auto.preview_url,
                status: auto.preview_status || 'starting',
                title: auto.title || scope.title,
              },
            };
            this.rememberScopedDevPreview(auto.preview_url, { scope, scopeKey });
            this.panelBrowserOpen = true;
            this.ensureWorkspacePreviewLayout(true);
          }
        }
        return data?.preview || null;
      } catch (e) {
        if (requestSeq !== this._workspacePreviewRequestSeq || this._workspacePreviewScopeKey !== scopeKey) return null;
        this.workspacePreview = {
          session: null,
          loading: false,
          error: e.message || 'Preview unavailable',
          workspace_id: scope.workspace_id,
          workspace_name: scope.workspace_name,
          auto_session_id: scope.auto_session_id,
        };
        this.clearScopedDevPreview({ scopeKey });
        return null;
      }
    },

    async ensureWorkspacePreview(options = {}) {
      const scope = this.currentPreviewScope();
      const scopeKey = this.currentPreviewScopeKey();
      if (!scope.workspace_id) {
        if (!options.silent) this.showToast('Select a workspace before opening the live page');
        return null;
      }
      const openExternal = options.openExternal === true;
      let restart = !!options.restart;
      const attachBrowser = options.attachBrowser !== false;
      let preview = this.currentWorkspacePreview();
      const previewStatus = String(preview?.status || '').toLowerCase();
      const stalePreview = /expo start/.test(String(preview?.command || '')) && /--host 127\.0\.0\.1/.test(String(preview?.command || ''));
      const missingAutoSourcePath = !!(scope.auto_session_id && !String(preview?.source_workspace_path || '').trim());
      if (!restart && (previewStatus === 'error' || previewStatus === 'stopped' || stalePreview || missingAutoSourcePath)) {
        restart = true;
      }
      if (!restart && preview?.url && ['running', 'starting'].includes(previewStatus)) {
        this.rememberScopedDevPreview(preview.url, { scope, scopeKey });
        this.panelBrowserOpen = true;
        this.ensureWorkspacePreviewLayout(true);
        if (openExternal) window.open(preview.url, '_blank', 'noopener,noreferrer');
        return preview;
      }

      this.workspacePreview = {
        ...(this.scopedWorkspacePreviewState?.() || blankPreviewState(scope)),
        loading: true,
        error: '',
        workspace_id: scope.workspace_id,
        workspace_name: scope.workspace_name,
        auto_session_id: scope.auto_session_id,
      };
      try {
        const payload = {
          auto_session_id: scope.auto_session_id || '',
          restart,
          attach_browser: attachBrowser,
        };
        const data = await this.api('POST', `/api/workspaces/${encodeURIComponent(scope.workspace_id)}/preview/start`, payload);
        if (this.currentPreviewScopeKey() !== scopeKey) return null;
        preview = data?.preview || null;
        this.workspacePreview = {
          session: preview,
          loading: false,
          error: '',
          workspace_id: scope.workspace_id,
          workspace_name: scope.workspace_name,
          auto_session_id: scope.auto_session_id,
        };
        if (data?.browser_actions) {
          this.browserActions = { ...this.browserActions, ...data.browser_actions };
        }
        if (preview?.url) {
          this.rememberScopedDevPreview(preview.url, { scope, scopeKey });
          this.panelBrowserOpen = true;
          this.ensureWorkspacePreviewLayout(true);
          if (openExternal) window.open(preview.url, '_blank', 'noopener,noreferrer');
          if (!options.silent) this.showToast(`Live preview ready for ${scope.workspace_name || 'workspace'}`);
        } else if (!options.silent) {
          this.showToast('Preview started, but no URL is available yet');
        }
        return preview;
      } catch (e) {
        if (this.currentPreviewScopeKey() !== scopeKey) return null;
        this.workspacePreview = {
          ...(this.scopedWorkspacePreviewState?.() || blankPreviewState(scope)),
          loading: false,
          error: e.message || 'Preview start failed',
          workspace_id: scope.workspace_id,
          workspace_name: scope.workspace_name,
          auto_session_id: scope.auto_session_id,
        };
        this.clearScopedDevPreview({ scopeKey });
        if (!options.silent) this.showToast(`Live preview failed: ${e.message || e}`);
        return null;
      }
    },

    async restartWorkspacePreview() {
      return this.ensureWorkspacePreview({ restart: true, openExternal: false, attachBrowser: true });
    },

    async stopWorkspacePreview() {
      const scope = this.currentPreviewScope();
      const scopeKey = this.currentPreviewScopeKey();
      if (!scope.workspace_id) return;
      try {
        const qs = new URLSearchParams();
        if (scope.auto_session_id) qs.set('auto_session_id', scope.auto_session_id);
        const data = await this.api('DELETE', `/api/workspaces/${encodeURIComponent(scope.workspace_id)}/preview${qs.toString() ? `?${qs.toString()}` : ''}`);
        if (this.currentPreviewScopeKey() !== scopeKey) return;
        this.workspacePreview = {
          ...(this.scopedWorkspacePreviewState?.() || blankPreviewState(scope)),
          session: data?.preview || null,
          loading: false,
          error: '',
          workspace_id: scope.workspace_id,
          workspace_name: scope.workspace_name,
          auto_session_id: scope.auto_session_id,
        };
        this.clearScopedDevPreview({ scopeKey });
        this.panelBrowserOpen = false;
        this.showToast('Live preview stopped');
      } catch (e) {
        this.showToast(`Could not stop live preview: ${e.message || e}`);
      }
    },

    workspaceTestUrl() {
      const auto = this.currentWorkspaceAutoSession?.() || null;
      const candidates = [
        this.currentWorkspacePreview?.()?.url,
        this.scopedDevPreview?.()?.url,
        auto?.preview_url,
        auto?.dev_url,
        this._workspaceEnv?.preview_url,
        this._workspaceEnv?.dev_url,
      ];
      for (const value of candidates) {
        const url = String(value || '').trim();
        if (!url) continue;
        if (/^https?:\/\//i.test(url)) return url;
      }
      return '';
    },

    async openWorkspaceTestTab() {
      const current = this.currentWorkspacePreview();
      const currentStatus = String(current?.status || '').toLowerCase();
      const shouldRestart =
        this.autonomousConsoleActive?.()
        || !current?.url
        || currentStatus === 'error'
        || currentStatus === 'stopped'
        || /--host 127\.0\.0\.1/.test(String(current?.command || ''));
      const preview = await this.ensureWorkspacePreview({
        openExternal: false,
        attachBrowser: true,
        restart: shouldRestart,
      });
      if (!preview?.url) {
        this.showToast('No test URL available for this workspace yet');
        return;
      }
      this.rememberScopedDevPreview(preview.url);
      this.panelBrowserOpen = true;
      this.ensureWorkspacePreviewLayout(true);
      this.showToast(`Testing ${this.currentPreviewScope().workspace_name || 'workspace'} inside Axon`);
    },

    _detectDevServerUrl(result) {
      try {
        if (!result || this.browserFrameUrl()) return;
        const scope = this.currentPreviewScope?.() || {};
        if (!String(scope.workspace_id || '').trim()) return;
        const matches = result.match(/https?:\/\/(?:localhost|127\.0\.0\.1):(\d{2,5})/g) || [];
        const url = matches.find(value => !value.includes(':7734'));
        if (url) {
          this.rememberScopedDevPreview(url, { scope });
          this.panelBrowserOpen = true;
        }
      } catch (_) {}
    },
  };
}

window.axonChatBrowserSurfaceMixin = axonChatBrowserSurfaceMixin;
