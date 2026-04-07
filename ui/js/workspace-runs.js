/* ══════════════════════════════════════════════════════════════
   Axon — Workspace Run State
   ══════════════════════════════════════════════════════════════ */

function axonWorkspaceRunsMixin() {
  const LIVE_OPERATOR_FEED_LIMIT = 12;

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
    isChatLoadingHere() {
      return !!this.currentWorkspaceRunActive?.();
    },

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
          mismatch: null,
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

    currentWorkspaceRunMismatch() {
      const state = this.workspaceRunStateFor();
      return state?.mismatch || null;
    },

    workspaceRunIsActive(workspaceId = null) {
      return !!this.workspaceRunStateFor(workspaceId).loading;
    },

    activeWorkspaceRuns() {
      return this.workspaceRunEntries()
        .filter(entry => entry.loading && entry.key !== '__all__')
        .map(entry => {
          const workspaceId = String(entry.key || '').trim();
          const project = (this.projects || []).find(p => String(p.id) === workspaceId);
          return {
            workspaceId,
            label: project?.name || `Workspace ${workspaceId}`,
            queueSize: Array.isArray(entry.queue) ? entry.queue.length : 0,
            phase: String(entry.liveOperator?.phase || 'observe'),
          };
        });
    },

    activeWorkspaceRunCount() {
      return this.activeWorkspaceRuns().length;
    },

    firstOtherActiveWorkspaceId() {
      const currentKey = this.workspaceRunKey();
      const match = this.workspaceRunEntries().find(entry => entry.loading && entry.key !== currentKey);
      if (!match || match.key === '__all__') return '';
      return match.key;
    },

    crossWorkspaceAgentLabel() {
      if (!this.chatLoading || this.isChatLoadingHere()) return '';
      const otherRuns = this.activeWorkspaceRuns().filter(run => run.workspaceId !== String(this.chatProjectId || '').trim());
      if (!otherRuns.length) return '';
      if (otherRuns.length === 1) return `${otherRuns[0].label} is running · Tap to follow`;
      return `${otherRuns.length} other workspaces are running · Tap to follow`;
    },

    consoleWorkspaceTargetHint() {
      const workspaceId = String(this.chatProjectId || '').trim();
      if (workspaceId) {
        const label = this.workspaceTabLabel?.(workspaceId) || `Workspace ${workspaceId}`;
        if (this.workspaceRunIsActive(workspaceId)) return `${label} is the active run target. You can steer it, queue more work, or switch tabs and follow another workspace.`;
        return `${label} is the selected run target. New agent and local-tool runs start here.`;
      }
      if (this.activeWorkspaceRunCount()) {
        return 'All workspaces is overview mode. Pick a workspace tab before starting a new agent or local-tool run.';
      }
      return 'All workspaces is overview mode. Pick a workspace tab when you want Axon to edit, scan, or open a live page.';
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
      if (loading) state.mismatch = null;
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
      state.liveOperatorFeed = [...state.liveOperatorFeed.slice(-(LIVE_OPERATOR_FEED_LIMIT - 1)), entry];
      this.refreshWorkspaceRunBindings();
    },

    beginWorkspaceLiveOperator(workspaceId = null, mode = 'chat', msg = '') {
      const state = this.workspaceRunStateFor(workspaceId);
      if (state.liveOperatorTimer) clearTimeout(state.liveOperatorTimer);
      const normalizedWorkspaceId = state.key === '__all__' ? '' : state.key;
      state.mismatch = null;
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

    recordWorkspaceRunMismatch(expectedWorkspaceId = '', reportedWorkspaceId = '', event = {}) {
      const expected = String(expectedWorkspaceId || '').trim();
      const reported = String(reportedWorkspaceId || '').trim();
      if (!expected || !reported || expected === reported) return null;
      const state = this.workspaceRunStateFor(expected);
      state.mismatch = {
        expectedWorkspaceId: expected,
        expectedLabel: this.workspaceTabLabel?.(expected) || `Workspace ${expected}`,
        reportedWorkspaceId: reported,
        reportedLabel: this.workspaceTabLabel?.(reported) || `Workspace ${reported}`,
        eventType: String(event?.type || '').trim() || 'runtime_event',
        at: new Date().toISOString(),
      };
      this.pushWorkspaceLiveOperatorFeed?.(
        expected,
        'recover',
        'Workspace routing mismatch',
        `Axon started this run in ${state.mismatch.expectedLabel}, but the runtime reported ${state.mismatch.reportedLabel}.`,
      );
      this.refreshWorkspaceRunBindings();
      return state.mismatch;
    },

    syncWorkspaceLiveOperatorSnapshot(snapshot = {}) {
      if (!snapshot || typeof snapshot !== 'object') return;
      const workspaceId = String(snapshot.workspace_id || '').trim();
      const state = this.workspaceRunStateFor(workspaceId);
      const autoSessionId = String(snapshot.auto_session_id || '').trim();
      if (!snapshot.active && !autoSessionId) {
        state.loading = false;
        this.clearWorkspaceLiveOperator(workspaceId, 0);
        return;
      }
      state.loading = !!snapshot.active;
      this.patchWorkspaceLiveOperator(workspaceId, {
        active: !!snapshot.active,
        mode: snapshot.mode || state.liveOperator.mode || 'chat',
        phase: snapshot.phase || state.liveOperator.phase || 'observe',
        title: snapshot.title || state.liveOperator.title || 'Axon is working…',
        detail: snapshot.detail || snapshot.summary || state.liveOperator.detail || '',
        tool: snapshot.tool || state.liveOperator.tool || '',
        startedAt: snapshot.started_at || state.liveOperator.startedAt || '',
        autoSessionId: autoSessionId || String(state.liveOperator.autoSessionId || '').trim(),
        updatedAt: snapshot.updated_at || state.liveOperator.updatedAt || new Date().toISOString(),
      });
      if (Array.isArray(snapshot.feed) && snapshot.feed.length) {
        state.liveOperatorFeed = snapshot.feed.slice(-LIVE_OPERATOR_FEED_LIMIT).map(entry => ({
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
        state.mismatch = null;
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
