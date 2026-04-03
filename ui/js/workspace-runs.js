/* ══════════════════════════════════════════════════════════════
   Axon — Workspace Run State
   ══════════════════════════════════════════════════════════════ */

function axonWorkspaceRunsMixin() {
  const defaultLiveOperator = (workspaceId = '') => ({
    active: false,
    mode: 'chat',
    phase: 'observe',
    title: '',
    detail: '',
    tool: '',
    startedAt: '',
    workspaceId: String(workspaceId || '').trim(),
    autoSessionId: '',
    updatedAt: '',
  });

  return {
    workspaceRunKey(workspaceId = null) {
      const raw = workspaceId == null ? this.chatProjectId : workspaceId;
      const value = String(raw || '').trim();
      return value || '__all__';
    },

    ensureWorkspaceRunRegistry() {
      if (!this._workspaceRunRegistry || typeof this._workspaceRunRegistry !== 'object') {
        this._workspaceRunRegistry = {};
      }
      return this._workspaceRunRegistry;
    },

    workspaceRunStateFor(workspaceId = null) {
      const key = this.workspaceRunKey(workspaceId);
      const registry = this.ensureWorkspaceRunRegistry();
      if (!registry[key]) {
        registry[key] = {
          key,
          loading: false,
          abortController: null,
          queue: [],
          liveOperator: defaultLiveOperator(key === '__all__' ? '' : key),
          liveOperatorFeed: [],
          liveOperatorTimer: null,
        };
      }
      return registry[key];
    },

    workspaceRunEntries() {
      return Object.values(this.ensureWorkspaceRunRegistry());
    },

    currentWorkspaceRunActive() {
      return !!this.workspaceRunStateFor().loading;
    },

    firstOtherActiveWorkspaceId() {
      const currentKey = this.workspaceRunKey();
      const match = this.workspaceRunEntries().find(entry => entry.loading && entry.key !== currentKey);
      if (!match || match.key === '__all__') return '';
      return match.key;
    },

    refreshWorkspaceRunBindings() {
      const current = this.workspaceRunStateFor();
      const entries = this.workspaceRunEntries();
      const anyActive = entries.some(entry => entry.loading);
      const crossWorkspaceId = this.firstOtherActiveWorkspaceId();

      this.chatLoading = anyActive;
      this._chatLoadingWorkspaceId = current.loading && current.key !== '__all__'
        ? current.key
        : crossWorkspaceId;
      this._chatAbortController = current.abortController || null;
      this.liveOperator = { ...defaultLiveOperator(current.key === '__all__' ? '' : current.key), ...(current.liveOperator || {}) };
      this.liveOperatorFeed = Array.isArray(current.liveOperatorFeed) ? [...current.liveOperatorFeed] : [];
    },

    setWorkspaceRunLoading(workspaceId = null, loading = false) {
      const state = this.workspaceRunStateFor(workspaceId);
      state.loading = !!loading;
      if (!loading) state.abortController = null;
      this.refreshWorkspaceRunBindings();
      return state;
    },

    setWorkspaceAbortController(workspaceId = null, controller = null) {
      const state = this.workspaceRunStateFor(workspaceId);
      state.abortController = controller || null;
      this.refreshWorkspaceRunBindings();
      return state.abortController;
    },

    stopWorkspaceRun(workspaceId = null) {
      const state = this.workspaceRunStateFor(workspaceId);
      if (state.abortController) {
        try { state.abortController.abort(); } catch (_) {}
      }
      state.abortController = null;
      state.loading = false;
      this.refreshWorkspaceRunBindings();
    },

    queueWorkspaceMessage(workspaceId = null, text = '') {
      const state = this.workspaceRunStateFor(workspaceId);
      state.queue.push(String(text || ''));
      return state.queue.length;
    },

    shiftWorkspaceMessage(workspaceId = null) {
      const state = this.workspaceRunStateFor(workspaceId);
      return state.queue.shift() || '';
    },

    workspaceQueueSize(workspaceId = null) {
      return this.workspaceRunStateFor(workspaceId).queue.length;
    },

    pushWorkspaceLiveOperatorFeed(workspaceId = null, phase = 'observe', title = 'Working', detail = '') {
      const state = this.workspaceRunStateFor(workspaceId);
      const entry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        phase: phase || 'observe',
        title: title || 'Working',
        detail: detail || '',
        at: new Date().toISOString(),
      };
      const last = state.liveOperatorFeed[state.liveOperatorFeed.length - 1];
      if (last && last.phase === entry.phase && last.title === entry.title && last.detail === entry.detail) return;
      state.liveOperatorFeed = [...state.liveOperatorFeed.slice(-5), entry];
      this.refreshWorkspaceRunBindings();
    },

    beginWorkspaceLiveOperator(workspaceId = null, mode = 'chat', msg = '') {
      const state = this.workspaceRunStateFor(workspaceId);
      if (state.liveOperatorTimer) clearTimeout(state.liveOperatorTimer);
      const normalizedWorkspaceId = state.key === '__all__' ? '' : state.key;
      state.liveOperator = {
        active: true,
        mode,
        phase: mode === 'agent' ? 'observe' : 'plan',
        title: mode === 'agent' ? 'Observing the task' : 'Opening the reply stream',
        detail: mode === 'agent'
          ? 'Axon is checking your goal and lining up the first safe step.'
          : 'Axon is preparing a response.',
        tool: '',
        startedAt: new Date().toISOString(),
        workspaceId: normalizedWorkspaceId,
        autoSessionId: '',
        updatedAt: new Date().toISOString(),
      };
      state.liveOperatorFeed = [];
      this.pushWorkspaceLiveOperatorFeed(
        normalizedWorkspaceId,
        state.liveOperator.phase,
        state.liveOperator.title,
        msg ? `Goal received: ${msg.slice(0, 120)}` : state.liveOperator.detail,
      );
      this.refreshWorkspaceRunBindings();
      return state.liveOperator;
    },

    patchWorkspaceLiveOperator(workspaceId = null, patch = {}) {
      const state = this.workspaceRunStateFor(workspaceId);
      const normalizedWorkspaceId = state.key === '__all__' ? '' : state.key;
      state.liveOperator = {
        ...defaultLiveOperator(normalizedWorkspaceId),
        ...(state.liveOperator || {}),
        ...patch,
        workspaceId: String(
          patch.workspaceId
          || patch.workspace_id
          || state.liveOperator?.workspaceId
          || normalizedWorkspaceId
          || ''
        ).trim(),
      };
      this.refreshWorkspaceRunBindings();
      return state.liveOperator;
    },

    syncWorkspaceLiveOperatorSnapshot(snapshot = {}) {
      if (!snapshot || typeof snapshot !== 'object') return;
      const workspaceId = String(snapshot.workspace_id || '').trim();
      const state = this.workspaceRunStateFor(workspaceId);
      if (!snapshot.active) {
        if (!state.loading) this.clearWorkspaceLiveOperator(workspaceId, 0);
        return;
      }
      this.patchWorkspaceLiveOperator(workspaceId, {
        active: true,
        mode: snapshot.mode || state.liveOperator.mode || 'chat',
        phase: snapshot.phase || state.liveOperator.phase || 'observe',
        title: snapshot.title || state.liveOperator.title || 'Axon is working…',
        detail: snapshot.detail || snapshot.summary || state.liveOperator.detail || '',
        tool: snapshot.tool || state.liveOperator.tool || '',
        startedAt: snapshot.started_at || state.liveOperator.startedAt || '',
        autoSessionId: String(snapshot.auto_session_id || state.liveOperator.autoSessionId || '').trim(),
        updatedAt: snapshot.updated_at || state.liveOperator.updatedAt || new Date().toISOString(),
      });
      if (Array.isArray(snapshot.feed) && snapshot.feed.length) {
        state.liveOperatorFeed = snapshot.feed.slice(-6).map(entry => ({
          id: String(entry?.id || `${entry?.at || Date.now()}-${entry?.phase || 'observe'}`),
          phase: String(entry?.phase || 'observe'),
          title: String(entry?.title || 'Working'),
          detail: String(entry?.detail || ''),
          at: String(entry?.at || new Date().toISOString()),
        }));
      }
      this.refreshWorkspaceRunBindings();
    },

    clearWorkspaceLiveOperator(workspaceId = null, delay = 0) {
      const state = this.workspaceRunStateFor(workspaceId);
      if (state.liveOperatorTimer) clearTimeout(state.liveOperatorTimer);
      const normalizedWorkspaceId = state.key === '__all__' ? '' : state.key;
      const reset = () => {
        state.liveOperator = defaultLiveOperator(normalizedWorkspaceId);
        state.liveOperatorFeed = [];
        if (String(this.chatProjectId || '').trim() === normalizedWorkspaceId) {
          this.stopDesktopPreview?.();
        }
        this.refreshWorkspaceRunBindings();
      };
      if (delay > 0) {
        state.liveOperatorTimer = setTimeout(reset, delay);
      } else {
        reset();
      }
    },
  };
}

window.axonWorkspaceRunsMixin = axonWorkspaceRunsMixin;
