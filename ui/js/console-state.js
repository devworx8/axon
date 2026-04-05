/* ══════════════════════════════════════════════════════════════
   Axon — Console shell state
   ══════════════════════════════════════════════════════════════ */

function axonConsoleStateMixin() {
  const DEFAULT_SIDEBAR_WIDTH = 420;
  const MIN_SIDEBAR_WIDTH = 340;
  const MAX_SIDEBAR_WIDTH = 620;
  const MAX_COMPOSER_HISTORY = 40;

  const parseJson = (value, fallback) => {
    const raw = String(value || '').trim();
    if (!raw) return fallback;
    try {
      const parsed = JSON.parse(raw);
      return parsed == null ? fallback : parsed;
    } catch (_) {
      return fallback;
    }
  };

  const uniqueStrings = (values = []) => {
    const seen = new Set();
    const output = [];
    (values || []).forEach((value) => {
      const next = String(value || '').trim();
      const key = next || '__all__';
      if (seen.has(key)) return;
      seen.add(key);
      output.push(next);
    });
    return output;
  };

  return {
    windowId: '',
    windowPinnedProjectId: '',
    consoleWorkspaceTabs: [''],
    workspaceTabMenuOpen: false,
    consoleSidebarWidth: DEFAULT_SIDEBAR_WIDTH,
    _consoleStateReady: false,
    _consoleStateWatchersBound: false,
    _consoleDraftPersistTimer: null,
    _composerHistory: [],
    _composerHistoryIndex: -1,
    _composerHistoryDraft: '',
    windowChannel: null,

    consoleStorageKey(key = '') {
      const scope = String(this.windowId || 'shared').trim() || 'shared';
      return `axon.console.${scope}.${key}`;
    },

    readWindowPref(key, fallback = '') {
      try {
        const scoped = localStorage.getItem(this.consoleStorageKey(key));
        if (scoped != null) return scoped;
      } catch (_) {}
      return fallback;
    },

    writeWindowPref(key, value) {
      try {
        const storageKey = this.consoleStorageKey(key);
        if (value == null || value === '') {
          localStorage.removeItem(storageKey);
          return;
        }
        localStorage.setItem(storageKey, String(value));
      } catch (_) {}
    },

    initConsoleWindowScope() {
      if (this._consoleStateReady) return;
      const href = String(window?.location?.href || 'http://localhost:7734/');
      const url = new URL(href);
      const explicitWindowId = String(url.searchParams.get('window') || '').trim();
      const explicitWorkspaceId = String(url.searchParams.get('workspace_id') || '').trim();
      let sessionWindowId = '';
      try {
        sessionWindowId = String(sessionStorage.getItem('axon.console.windowId') || '').trim();
      } catch (_) {}
      const resolvedWindowId = explicitWindowId
        || sessionWindowId
        || `console-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

      this.windowId = resolvedWindowId;
      this.windowPinnedProjectId = explicitWorkspaceId;
      try {
        sessionStorage.setItem('axon.console.windowId', resolvedWindowId);
      } catch (_) {}
      if (String(url.searchParams.get('view') || '').trim() === 'chat') {
        this.activeTab = 'chat';
      } else {
        const savedTab = String(this.readWindowPref('activeTab', this.activeTab || 'dashboard') || '').trim();
        if (savedTab) this.activeTab = savedTab;
      }

      const savedWidth = Number(this.readWindowPref('consoleSidebarWidth', DEFAULT_SIDEBAR_WIDTH));
      if (Number.isFinite(savedWidth) && savedWidth > 0) {
        this.consoleSidebarWidth = savedWidth;
      }
      this.showConsoleDetails = this.readWindowPref('showConsoleDetails', this.showConsoleDetails ? 'true' : 'false') === 'true';
      this._composerHistory = Array.isArray(parseJson(this.readWindowPref('composerHistory', '[]'), []))
        ? parseJson(this.readWindowPref('composerHistory', '[]'), []).map((value) => String(value || '').trim()).filter(Boolean)
        : [];
      const savedDraft = String(this.readWindowPref('composerDraft', '') || '');
      if (savedDraft && !String(this.chatInput || '').trim()) this.chatInput = savedDraft;
      this.consoleWorkspaceTabs = this.restoreWorkspaceTabs();
      this._bindConsoleBroadcastChannel();
      this._consoleStateReady = true;
    },

    _bindConsoleBroadcastChannel() {
      if (this.windowChannel || typeof BroadcastChannel !== 'function') return;
      try {
        this.windowChannel = new BroadcastChannel('axon-console-shell');
        this.windowChannel.onmessage = (event) => {
          const data = event?.data || {};
          if (!data || data.source === this.windowId) return;
          if (data.type === 'workspace_deleted') {
            const projectId = String(data.payload?.projectId || '').trim();
            if (!projectId) return;
            this.consoleWorkspaceTabs = (this.consoleWorkspaceTabs || []).filter((value) => String(value || '').trim() !== projectId);
            if (String(this.chatProjectId || '').trim() === projectId) {
              this.activateWorkspaceTab(this.windowPinnedProjectId || '');
            } else {
              this.syncWorkspaceTabs();
              this.persistConsoleWindowState();
            }
          }
        };
      } catch (_) {
        this.windowChannel = null;
      }
    },

    bindConsoleStateWatchers() {
      if (this._consoleStateWatchersBound || typeof this.$watch !== 'function') return;
      this.$watch('activeTab', () => this.persistConsoleWindowState());
      this.$watch('chatProjectId', () => this.persistConsoleWindowState());
      this.$watch('showConsoleDetails', () => this.persistConsoleWindowState());
      this.$watch('chatInput', () => this.schedulePersistComposerDraft());
      this._consoleStateWatchersBound = true;
    },

    restoreWorkspaceTabs() {
      const pinned = String(this.windowPinnedProjectId || '').trim();
      if (pinned) return [pinned];

      const parsed = parseJson(this.readWindowPref('workspaceTabs', '[""]'), ['']);
      const rawTabs = Array.isArray(parsed) ? parsed : [''];
      const savedWorkspaceId = String(this.readWindowPref('selectedWorkspaceId', this.chatProjectId || '') || '').trim();
      const normalized = uniqueStrings([...rawTabs, savedWorkspaceId]);
      if (!normalized.length) normalized.push('');
      if (!normalized.includes('')) normalized.unshift('');
      return normalized;
    },

    persistConsoleWindowState() {
      this.writeWindowPref('activeTab', this.activeTab || 'dashboard');
      this.writeWindowPref('selectedWorkspaceId', String(this.chatProjectId || '').trim());
      this.writeWindowPref('workspaceTabs', JSON.stringify(this.consoleWorkspaceTabs || ['']));
      this.writeWindowPref('showConsoleDetails', this.showConsoleDetails ? 'true' : 'false');
      this.writeWindowPref('consoleSidebarWidth', String(Math.round(this.consoleSidebarWidth || DEFAULT_SIDEBAR_WIDTH)));
    },

    schedulePersistComposerDraft() {
      if (!this._consoleStateReady) return;
      if (typeof setTimeout !== 'function') {
        this.writeWindowPref('composerDraft', this.chatInput || '');
        return;
      }
      if (this._consoleDraftPersistTimer && typeof clearTimeout === 'function') {
        clearTimeout(this._consoleDraftPersistTimer);
      }
      this._consoleDraftPersistTimer = setTimeout(() => {
        this.writeWindowPref('composerDraft', this.chatInput || '');
      }, 120);
    },

    persistComposerHistory() {
      this.writeWindowPref('composerHistory', JSON.stringify((this._composerHistory || []).slice(-MAX_COMPOSER_HISTORY)));
    },

    rememberComposerHistory(text = '') {
      const message = String(text || '').trim();
      if (!message) return;
      const filtered = (this._composerHistory || []).filter((entry) => String(entry || '').trim() !== message);
      filtered.push(message);
      this._composerHistory = filtered.slice(-MAX_COMPOSER_HISTORY);
      this._composerHistoryIndex = -1;
      this._composerHistoryDraft = '';
      this.persistComposerHistory();
      this.writeWindowPref('composerDraft', '');
    },

    handleComposerHistoryKey(event, direction = 'up') {
      if (!event || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const composer = this.$refs?.chatComposer || null;
      const value = String(this.chatInput || '');
      const selectionStart = Number(composer?.selectionStart ?? value.length);
      const selectionEnd = Number(composer?.selectionEnd ?? value.length);
      if (selectionStart !== selectionEnd) return;
      if (direction === 'up' && this._composerHistoryIndex === -1 && selectionStart !== 0 && value.trim()) return;
      if (direction === 'down' && selectionEnd !== value.length) return;
      if (!Array.isArray(this._composerHistory) || !this._composerHistory.length) return;

      event.preventDefault();
      if (direction === 'up') {
        if (this._composerHistoryIndex === -1) {
          this._composerHistoryDraft = value;
          this._composerHistoryIndex = this._composerHistory.length - 1;
        } else if (this._composerHistoryIndex > 0) {
          this._composerHistoryIndex -= 1;
        }
      } else {
        if (this._composerHistoryIndex === -1) return;
        if (this._composerHistoryIndex < this._composerHistory.length - 1) {
          this._composerHistoryIndex += 1;
        } else {
          this._composerHistoryIndex = -1;
          this.chatInput = this._composerHistoryDraft || '';
          this.$nextTick?.(() => {
            this.resetChatComposerHeight?.();
            const nextComposer = this.$refs?.chatComposer || null;
            const length = String(this.chatInput || '').length;
            nextComposer?.setSelectionRange?.(length, length);
          });
          this.schedulePersistComposerDraft();
          return;
        }
      }

      this.chatInput = this._composerHistory[this._composerHistoryIndex] || '';
      this.$nextTick?.(() => {
        this.resetChatComposerHeight?.();
        const nextComposer = this.$refs?.chatComposer || null;
        const length = String(this.chatInput || '').length;
        nextComposer?.focus?.();
        nextComposer?.setSelectionRange?.(length, length);
      });
      this.schedulePersistComposerDraft();
    },

    restoreConsoleWindowState() {
      this.initConsoleWindowScope();
      this.bindConsoleStateWatchers();
      this.showConsoleDetails = this.readWindowPref('showConsoleDetails', this.showConsoleDetails ? 'true' : 'false') === 'true';

      const pinned = String(this.windowPinnedProjectId || '').trim();
      const savedWorkspaceId = pinned || String(this.readWindowPref('selectedWorkspaceId', '') || '').trim();
      this.consoleWorkspaceTabs = this.restoreWorkspaceTabs();
      this.syncWorkspaceTabs();

      const savedWorkspaceExists = savedWorkspaceId
        ? (this.projects || []).some((project) => String(project?.id || '').trim() === savedWorkspaceId)
        : true;
      const targetWorkspaceId = savedWorkspaceExists ? savedWorkspaceId : '';

      this.chatProjectId = targetWorkspaceId;
      this.chatProject = (this.projects || []).find((project) => String(project?.id || '').trim() === targetWorkspaceId) || null;
      if (typeof this.updateChatProject === 'function') {
        this.updateChatProject();
      } else if (typeof this.loadChatHistory === 'function' && this.activeTab === 'chat') {
        this.loadChatHistory();
      }
      if (typeof this.restoreConversationModePreference === 'function') {
        this.restoreConversationModePreference({ workspaceId: targetWorkspaceId || '' });
      }
      this.persistConsoleWindowState();
      this.$nextTick?.(() => this.resetChatComposerHeight?.());
    },

    syncWorkspaceTabs() {
      const pinned = String(this.windowPinnedProjectId || '').trim();
      if (pinned) {
        this.consoleWorkspaceTabs = [pinned];
        if (String(this.chatProjectId || '').trim() !== pinned) this.chatProjectId = pinned;
        return this.consoleWorkspaceTabs;
      }

      const knownProjects = new Set((this.projects || []).map((project) => String(project?.id || '').trim()).filter(Boolean));
      const nextTabs = uniqueStrings((this.consoleWorkspaceTabs || []).filter((value) => {
        const key = String(value || '').trim();
        return !key || knownProjects.has(key);
      }));
      if (!nextTabs.length) nextTabs.push('');
      if (!nextTabs.includes('')) nextTabs.unshift('');
      this.consoleWorkspaceTabs = nextTabs;

      const activeWorkspaceId = String(this.chatProjectId || '').trim();
      if (activeWorkspaceId && !nextTabs.includes(activeWorkspaceId)) {
        this.chatProjectId = '';
      }
      this.persistConsoleWindowState();
      return this.consoleWorkspaceTabs;
    },

    workspaceTabKey(projectId = '') {
      const value = String(projectId || '').trim();
      return value || '__all__';
    },

    workspaceTabLabel(projectId = '') {
      const value = String(projectId || '').trim();
      if (!value) return 'All workspaces';
      const project = (this.projects || []).find((entry) => String(entry?.id || '').trim() === value);
      return String(project?.name || `Workspace ${value}`).trim();
    },

    workspaceTabDisplayLabel(projectId = '') {
      const value = String(projectId || '').trim();
      if (!value) return 'All';
      return this.workspaceTabLabel(value);
    },

    availableWorkspaceTabProjects() {
      const openTabs = new Set((this.consoleWorkspaceTabs || []).map((value) => String(value || '').trim()).filter(Boolean));
      return (this.projects || []).filter((project) => !openTabs.has(String(project?.id || '').trim()));
    },

    ensureWorkspaceTab(projectId = '') {
      const pinned = String(this.windowPinnedProjectId || '').trim();
      const value = pinned || String(projectId || '').trim();
      if (pinned) {
        this.consoleWorkspaceTabs = [pinned];
        return pinned;
      }
      const nextTabs = uniqueStrings([...(this.consoleWorkspaceTabs || []), value]);
      if (!nextTabs.length) nextTabs.push('');
      if (!nextTabs.includes('')) nextTabs.unshift('');
      this.consoleWorkspaceTabs = nextTabs;
      this.persistConsoleWindowState();
      return value;
    },

    addWorkspaceTab(projectId = '') {
      this.workspaceTabMenuOpen = false;
      return this.activateWorkspaceTab(projectId);
    },

    activateWorkspaceTab(projectId = '') {
      const target = this.ensureWorkspaceTab(projectId);
      this.chatProjectId = String(target || '').trim();
      this.persistConsoleWindowState();
      this.updateChatProject?.();
      return this.chatProjectId;
    },

    closeWorkspaceTab(projectId = '') {
      const pinned = String(this.windowPinnedProjectId || '').trim();
      const value = String(projectId || '').trim();
      if (!value || pinned) return;

      const nextTabs = (this.consoleWorkspaceTabs || []).filter((tabId) => String(tabId || '').trim() !== value);
      this.consoleWorkspaceTabs = nextTabs.length ? nextTabs : [''];
      if (String(this.chatProjectId || '').trim() === value) {
        const fallback = this.consoleWorkspaceTabs.find((tabId) => String(tabId || '').trim()) || '';
        this.chatProjectId = fallback;
        this.updateChatProject?.();
      }
      this.persistConsoleWindowState();
    },

    canClearConsoleWorkspaceSelection() {
      return !!String(this.chatProjectId || '').trim() && !String(this.windowPinnedProjectId || '').trim();
    },

    clearConsoleWorkspaceSelection() {
      if (!this.canClearConsoleWorkspaceSelection()) return;
      this.activateWorkspaceTab('');
    },

    _openConsoleWindow(workspaceId = '', pinned = false) {
      const url = new URL(String(window?.location?.href || 'http://localhost:7734/'));
      const nextWindowId = `console-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      url.searchParams.set('view', 'chat');
      url.searchParams.set('window', nextWindowId);
      if (pinned && workspaceId) url.searchParams.set('workspace_id', String(workspaceId));
      else url.searchParams.delete('workspace_id');
      window.open(url.toString(), '_blank', 'noopener,noreferrer');
    },

    openConsoleInNewWindow() {
      this._openConsoleWindow('', false);
    },

    openWorkspaceInNewWindow(projectId = '') {
      const workspaceId = String(projectId || this.chatProjectId || '').trim();
      this._openConsoleWindow(workspaceId, !!workspaceId);
    },

    consoleSidebarStyle() {
      if (this.isMobile) return '';
      const width = Number(this.consoleSidebarWidth || DEFAULT_SIDEBAR_WIDTH);
      const clamped = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, width));
      return `width:${clamped}px;flex-basis:${clamped}px;`;
    },

    setConsoleSidebarWidth(nextWidth) {
      if (!Number.isFinite(Number(nextWidth))) return;
      const viewportWidth = Number(window?.innerWidth || 1440);
      const maxWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, viewportWidth - 320));
      const clamped = Math.max(MIN_SIDEBAR_WIDTH, Math.min(maxWidth, Number(nextWidth)));
      this.consoleSidebarWidth = clamped;
      this.persistConsoleWindowState();
    },

    startConsoleResize(event) {
      if (this.isMobile) return;
      event.preventDefault?.();
      const onMove = (moveEvent) => {
        this.setConsoleSidebarWidth((window?.innerWidth || 1440) - Number(moveEvent?.clientX || 0));
      };
      const stop = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
    },

    editUserMessage(message = {}) {
      this.chatInput = String(message?.content || '').trim();
      this.switchTab?.('chat');
      this.$nextTick?.(() => {
        this.resetChatComposerHeight?.();
        const composer = this.$refs?.chatComposer || null;
        const length = String(this.chatInput || '').length;
        composer?.focus?.();
        composer?.setSelectionRange?.(length, length);
      });
      this.schedulePersistComposerDraft();
    },

    copyChatMessage(message = {}) {
      this.copyToClipboard?.(message?.content || '', message?.role === 'user' ? 'Message' : 'Markdown');
    },
  };
}

window.axonConsoleStateMixin = axonConsoleStateMixin;
