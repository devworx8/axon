/* ══════════════════════════════════════════════════════════════
   Axon — Voice File Viewer (Holographic)
   ══════════════════════════════════════════════════════════════ */

function axonVoiceFileViewerMixin() {
  const escapeHtml = (value = '') => String(value || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const trimText = (value = '') => String(value || '').trim();
  const toPosix = (value = '') => String(value || '').replace(/\\/g, '/');
  const basename = (value = '') => {
    const raw = trimText(value).replace(/\/+$/, '');
    if (!raw) return '';
    if (/^https?:\/\//i.test(raw)) {
      try { return new URL(raw).hostname; } catch (_) { return raw; }
    }
    const parts = raw.split('/');
    return parts[parts.length - 1] || raw;
  };
  const collapsePath = (value = '') => {
    const raw = toPosix(trimText(value));
    if (!raw) return '';
    const absolute = raw.startsWith('/');
    const parts = [];
    raw.split('/').forEach((segment) => {
      if (!segment || segment === '.') return;
      if (segment === '..') {
        if (parts.length && parts[parts.length - 1] !== '..') {
          parts.pop();
        } else if (!absolute) {
          parts.push('..');
        }
        return;
      }
      parts.push(segment);
    });
    const joined = parts.join('/');
    if (!joined) return absolute ? '/' : '';
    return absolute ? `/${joined}` : joined;
  };
  const joinPath = (base = '', relative = '') => {
    const prefix = trimText(base).replace(/\/+$/, '');
    const suffix = trimText(relative).replace(/^\/+/, '');
    return collapsePath([prefix, suffix].filter(Boolean).join('/'));
  };
  const WORKSPACE_UI_HINT_PREFIXES = ['js/', 'css/', 'partials/'];
  const WORKSPACE_PATH_HINTS = [
    'ui/',
    'tests/',
    'apps/',
    'axon_api/',
    'axon_core/',
    'design/',
    'docs/',
    'scripts/',
    'server.py',
    'brain.py',
    'resource_bank.py',
    'requirements.txt',
  ];
  const SAFE_LOCAL_PREFIXES = ['/home/', '/tmp/', '/var/tmp/', '~/'];

  return {
    voiceFileViewer: {
      open: false,
      path: '',
      type: '',
      content: '',
      items: [],
      parent: '',
      loading: false,
      error: '',
      notice: '',
      lastManualAt: 0,
      autoOpened: false,
    },
    voiceFileReveal: {
      queue: [],
      timerId: null,
      pausedUntil: 0,
      lastOpenAt: 0,
      active: false,
    },

    _ensureVoiceFileRevealState() {
      if (!this.voiceFileReveal || typeof this.voiceFileReveal !== 'object') {
        this.voiceFileReveal = {};
      }
      const state = this.voiceFileReveal;
      state.queue = Array.isArray(state.queue) ? state.queue : [];
      state.timerId = state.timerId || null;
      state.pausedUntil = Number.isFinite(Number(state.pausedUntil)) ? Number(state.pausedUntil) : 0;
      state.lastOpenAt = Number.isFinite(Number(state.lastOpenAt)) ? Number(state.lastOpenAt) : 0;
      state.lastOpenPath = trimText(state.lastOpenPath || '');
      state.active = !!state.active;
      return state;
    },

    voiceFileRevealActive() {
      const state = this._ensureVoiceFileRevealState();
      return !!(state.active || state.queue.length || state.timerId);
    },

    _resetVoiceFileViewerState() {
      if (!this.voiceFileViewer || typeof this.voiceFileViewer !== 'object') return;
      this.voiceFileViewer.open = false;
      this.voiceFileViewer.path = '';
      this.voiceFileViewer.type = '';
      this.voiceFileViewer.content = '';
      this.voiceFileViewer.items = [];
      this.voiceFileViewer.parent = '';
      this.voiceFileViewer.loading = false;
      this.voiceFileViewer.error = '';
      this.voiceFileViewer.notice = '';
      this.voiceFileViewer.autoOpened = false;
      this._renderFileViewerDOM();
    },

    resetVoiceFileRevealState(options = {}) {
      const state = this._ensureVoiceFileRevealState();
      if (state.timerId) {
        clearTimeout(state.timerId);
        state.timerId = null;
      }
      state.queue = [];
      state.pausedUntil = 0;
      state.active = false;
      state.lastOpenPath = '';
      if (options.closeViewer && this.voiceFileViewer?.open && this.voiceFileViewer?.autoOpened) {
        this._resetVoiceFileViewerState();
      }
    },

    _normalizeRevealPath(path = '') {
      const value = trimText(path);
      if (!value) return '';
      const cleaned = value
        .replace(/[#?].*$/, '')
        .replace(/:\d+(?::\d+)?$/, '')
        .replace(/[),.;:!?]+$/g, '');
      if (!cleaned) return '';
      if (/^https?:\/\//i.test(cleaned)) return cleaned;

      const roots = this._voiceWorkspaceRoots?.() || [];
      const primaryRoot = trimText(roots[0] || '');
      const normalized = this._resolveWorkspaceRelativePath?.(cleaned) || collapsePath(cleaned);
      if (SAFE_LOCAL_PREFIXES.some((prefix) => normalized.startsWith(prefix))) {
        return normalized;
      }
      if (primaryRoot && normalized === primaryRoot) {
        return normalized;
      }
      return '';
    },

    _voiceWorkspaceRoots() {
      const candidates = [
        this.currentWorkspaceAutoSession?.()?.source_workspace_path,
        this.currentWorkspaceAutoSession?.()?.workspace_path,
        this.chatProject?.path,
        this.browserSourcePath?.(),
        this.dashboardLiveTerminalSession?.()?.cwd,
        this.voiceTerminalSession?.()?.cwd,
        this.currentTerminalSession?.()?.cwd,
      ].map((item) => collapsePath(item)).filter(Boolean);
      return [...new Set(candidates)];
    },

    _resolveWorkspaceRelativePath(path = '') {
      const raw = trimText(path);
      if (!raw) return '';
      if (/^https?:\/\//i.test(raw)) return raw;
      if (SAFE_LOCAL_PREFIXES.some((prefix) => raw.startsWith(prefix))) {
        return collapsePath(raw);
      }

      const roots = this._voiceWorkspaceRoots?.() || [];
      const workspaceRoot = trimText(roots[0] || '');
      if (!workspaceRoot) return '';
      const uiRoot = joinPath(workspaceRoot, 'ui');

      if (raw.startsWith('./') || raw.startsWith('../')) {
        return joinPath(workspaceRoot, raw);
      }

      const withoutLeadingSlash = raw.replace(/^\/+/, '');
      if (raw.startsWith('/')) {
        if (WORKSPACE_UI_HINT_PREFIXES.some((prefix) => withoutLeadingSlash.startsWith(prefix))) {
          return joinPath(uiRoot, withoutLeadingSlash);
        }
        if (WORKSPACE_PATH_HINTS.some((prefix) => withoutLeadingSlash.startsWith(prefix))) {
          return joinPath(workspaceRoot, withoutLeadingSlash);
        }
        return '';
      }

      if (WORKSPACE_PATH_HINTS.some((prefix) => raw.startsWith(prefix))) {
        return joinPath(workspaceRoot, raw);
      }
      if (WORKSPACE_UI_HINT_PREFIXES.some((prefix) => raw.startsWith(prefix))) {
        return joinPath(uiRoot, raw);
      }
      return '';
    },

    _normalizeViewerPath(path = '', explicitKind = '') {
      const value = trimText(path);
      if (!value) return '';
      const forced = trimText(explicitKind).toLowerCase();
      if (forced === 'web' || /^https?:\/\//i.test(value)) return value;
      return this._normalizeRevealPath(value);
    },

    pauseVoiceFileReveal(ms = 6000) {
      const state = this._ensureVoiceFileRevealState();
      const until = Date.now() + Math.max(0, ms);
      state.pausedUntil = Math.max(state.pausedUntil || 0, until);
      if (state.timerId) {
        clearTimeout(state.timerId);
        state.timerId = null;
      }
    },

    queueVoiceFileReveal(paths, options = {}) {
      const state = this._ensureVoiceFileRevealState();
      const items = Array.isArray(paths) ? paths : [paths];
      const kind = trimText(options.kind || '');
      const delay = Number.isFinite(Number(options.delayMs)) ? Number(options.delayMs) : 900;
      const maxItems = Number.isFinite(Number(options.maxItems)) ? Number(options.maxItems) : 6;
      const dedupe = new Set(state.queue.map(entry => entry.path));
      const incoming = [];

      items.forEach((item) => {
        const normalized = this._normalizeRevealPath(item);
        if (!normalized || dedupe.has(normalized)) return;
        if (
          normalized === trimText(this.voiceFileViewer?.path)
          || (normalized === trimText(state.lastOpenPath) && (Date.now() - Number(state.lastOpenAt || 0)) < 4000)
        ) {
          return;
        }
        dedupe.add(normalized);
        incoming.push({
          path: normalized,
          kind,
          queuedAt: Date.now(),
        });
      });

      if (!incoming.length) return;
      state.queue = [...state.queue, ...incoming].slice(0, maxItems);
      state.active = true;
      state.revealDelay = delay;
      this._drainVoiceFileRevealQueue();
    },

    _drainVoiceFileRevealQueue() {
      const state = this._ensureVoiceFileRevealState();
      if (state.timerId) return;
      if (!state.queue.length) {
        state.active = false;
        return;
      }
      const now = Date.now();
      if (state.pausedUntil && now < state.pausedUntil) {
        state.timerId = setTimeout(() => {
          state.timerId = null;
          this._drainVoiceFileRevealQueue();
        }, Math.max(200, state.pausedUntil - now));
        return;
      }
      if (this.voiceFileViewer?.lastManualAt && (now - this.voiceFileViewer.lastManualAt) < 5000) {
        state.timerId = setTimeout(() => {
          state.timerId = null;
          this._drainVoiceFileRevealQueue();
        }, 1200);
        return;
      }
      const next = state.queue.shift();
      if (!next) {
        state.active = false;
        return;
      }
      if (typeof this.pushActivityEntry === 'function') {
        const kind = trimText(next.kind || this._detectFileType(next.path));
        const title = kind === 'folder' ? 'Opening folder' : 'Surfacing file';
        try {
          this.pushActivityEntry('execute', title, next.path, {
            filePath: next.path,
            tool: kind === 'folder' ? 'files/browse' : 'files/open',
          });
        } catch (_) {}
      }
      const alreadyOpen = !!(
        this.voiceFileViewer?.open
        && trimText(this.voiceFileViewer.path) === trimText(next.path)
        && trimText(this.voiceFileViewer.type) === trimText(next.kind || this._detectFileType(next.path))
      );
      if (!alreadyOpen) {
        this.openVoiceFileViewer?.(next.path, next.kind || '', { auto: true });
      }
      state.lastOpenAt = now;
      state.lastOpenPath = trimText(next.path);
      state.timerId = setTimeout(() => {
        state.timerId = null;
        this._drainVoiceFileRevealQueue();
      }, state.revealDelay || 900);
    },

    _detectFileType(path, explicitKind = '') {
      const forced = trimText(explicitKind).toLowerCase();
      if (forced) return forced;
      if (/^https?:\/\//i.test(path)) return 'web';
      const raw = trimText(path).replace(/\/+$/, '');
      const ext = raw.split('.').pop().toLowerCase();
      if (!ext || ext === raw.toLowerCase()) return 'folder';
      if ([
        'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
        'pages', 'numbers', 'key', 'rtf',
        'zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2',
      ].includes(ext)) return 'binary';
      if (ext === 'pdf') return 'pdf';
      if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'].includes(ext)) return 'image';
      if (['mp4', 'webm', 'mov', 'avi'].includes(ext)) return 'video';
      if (['mp3', 'wav', 'ogg', 'flac', 'm4a'].includes(ext)) return 'audio';
      if (['js', 'ts', 'tsx', 'jsx', 'py', 'css', 'html', 'json', 'yaml', 'yml',
           'sh', 'bash', 'sql', 'md', 'rs', 'go', 'java', 'c', 'cpp', 'h',
           'rb', 'php', 'swift', 'kt', 'toml', 'ini', 'cfg', 'env',
           'xml', 'csv', 'txt', 'log', 'conf'].includes(ext)) return 'code';
      return 'text';
    },

    _fileLanguage(path) {
      const ext = String(path || '').split('.').pop().toLowerCase();
      const map = {
        js: 'javascript', ts: 'typescript', tsx: 'tsx', jsx: 'jsx',
        py: 'python', css: 'css', html: 'html', json: 'json',
        yaml: 'yaml', yml: 'yaml', sh: 'bash', bash: 'bash',
        sql: 'sql', md: 'markdown', rs: 'rust', go: 'go',
        java: 'java', c: 'c', cpp: 'cpp', h: 'c',
        rb: 'ruby', php: 'php', swift: 'swift', kt: 'kotlin',
        xml: 'xml', csv: 'plaintext', txt: 'plaintext',
      };
      return map[ext] || 'plaintext';
    },

    _voiceFolderIcon(item = {}) {
      if (item?.is_dir) return '📁';
      return this._detectFileType(item?.path) === 'pdf' ? '📘' : '📄';
    },

    _voiceFolderRows(items = []) {
      return items.map((item) => {
        const kind = item?.is_dir ? 'folder' : this._detectFileType(item?.path);
        const size = item?.is_dir ? 'Folder' : (typeof this.formatBytes === 'function' ? this.formatBytes(item.size || 0) : `${item.size || 0} B`);
        return `<button type="button" class="voice-file-viewer__folder-entry" data-voice-path="${escapeHtml(item.path || '')}" data-voice-kind="${escapeHtml(kind)}">`
          + `<div class="voice-file-viewer__folder-icon">${escapeHtml(this._voiceFolderIcon(item))}</div>`
          + `<div class="voice-file-viewer__folder-copy">`
          + `<div class="voice-file-viewer__folder-name">${escapeHtml(item.name || 'Untitled')}</div>`
          + `<div class="voice-file-viewer__folder-meta">${escapeHtml(item?.is_dir ? 'Folder' : kind)} · ${escapeHtml(size)}</div>`
          + `</div>`
          + `<div class="voice-file-viewer__folder-action">${escapeHtml(item?.is_dir ? 'Browse' : 'Open')}</div>`
          + `</button>`;
      }).join('');
    },

    _renderFileViewerDOM() {
      const mount = document.getElementById('voice-file-viewer-mount');
      if (!mount) return;
      const v = this.voiceFileViewer;
      if (!v.open) {
        mount.innerHTML = '';
        return;
      }

      const url = this.voiceFileViewerUrl();
      const name = this.voiceFileName();
      let body = '';
      if (v.loading) {
        body = '<div class="voice-file-viewer__loading"><div class="voice-file-viewer__spinner"></div><span>Loading file…</span></div>';
      } else if (v.type === 'binary') {
        const note = trimText(v.notice) || 'Preview unavailable for this file type.';
        const openUrl = this.voiceFileViewerUrl();
        body = `<div class="voice-file-viewer__binary">`
          + `<div class="voice-file-viewer__binary-label">Binary file</div>`
          + `<div class="voice-file-viewer__binary-note">${escapeHtml(note)}</div>`
          + `<div class="voice-file-viewer__binary-actions">`
          + `<a class="voice-file-viewer__binary-btn" href="${escapeHtml(openUrl)}" target="_blank" rel="noreferrer">Open file</a>`
          + `<a class="voice-file-viewer__binary-btn voice-file-viewer__binary-btn--ghost" href="${escapeHtml(openUrl)}" download>Download</a>`
          + `</div>`
          + `</div>`;
      } else if (v.error) {
        body = `<div class="voice-file-viewer__error">${escapeHtml(v.error)}</div>`;
      } else if (v.type === 'folder') {
        const upButton = v.parent
          ? `<button type="button" class="voice-file-viewer__folder-up" data-voice-path="${escapeHtml(v.parent)}" data-voice-kind="folder">⬑ Up one level</button>`
          : '';
        const count = Array.isArray(v.items) ? v.items.length : 0;
        body = '<div class="voice-file-viewer__folder">'
          + '<div class="voice-file-viewer__folder-toolbar">'
          + upButton
          + `<div class="voice-file-viewer__folder-summary">${count} items visible</div>`
          + '</div>'
          + `<div class="voice-file-viewer__folder-list">${this._voiceFolderRows(v.items || []) || '<div class="voice-file-viewer__folder-empty">This folder is empty.</div>'}</div>`
          + '</div>';
      } else if (v.type === 'pdf') {
        body = `<iframe src="${escapeHtml(url)}" class="voice-file-viewer__iframe"></iframe>`;
      } else if (v.type === 'web') {
        body = `<iframe src="${escapeHtml(v.path)}" class="voice-file-viewer__iframe" sandbox="allow-scripts allow-same-origin allow-popups" referrerpolicy="no-referrer"></iframe>`;
      } else if (v.type === 'image') {
        body = `<img src="${escapeHtml(url)}" alt="${escapeHtml(name)}" class="voice-file-viewer__image">`;
      } else if (v.type === 'video') {
        body = `<video src="${escapeHtml(url)}" controls class="voice-file-viewer__video"></video>`;
      } else if (v.type === 'audio') {
        body = `<div class="voice-file-viewer__audio-wrap"><audio src="${escapeHtml(url)}" controls style="width:100%"></audio></div>`;
      } else {
        body = `<pre class="voice-file-viewer__code"><code>${v.content || escapeHtml('(empty)')}</code></pre>`;
      }

      mount.innerHTML = `
        <div class="voice-file-viewer-overlay" id="voice-file-viewer-overlay">
          <div class="voice-file-viewer">
            <div class="voice-file-viewer__bracket voice-file-viewer__bracket--tl"></div>
            <div class="voice-file-viewer__bracket voice-file-viewer__bracket--tr"></div>
            <div class="voice-file-viewer__bracket voice-file-viewer__bracket--bl"></div>
            <div class="voice-file-viewer__bracket voice-file-viewer__bracket--br"></div>
            <div class="voice-file-viewer__scanline"></div>
            <div class="voice-file-viewer__header">
              <div class="voice-file-viewer__header-left">
                <span class="voice-file-viewer__dot"></span>
                <span class="voice-file-viewer__title">${escapeHtml(name)}</span>
              </div>
              <div class="voice-file-viewer__path">${escapeHtml(v.path)}</div>
              <button class="voice-file-viewer__close" id="voice-file-viewer-close">✕</button>
            </div>
            <div class="voice-file-viewer__body">${body}</div>
          </div>
        </div>`;

      mount.querySelector('#voice-file-viewer-overlay')?.addEventListener('click', (event) => {
        if (event.target.id === 'voice-file-viewer-overlay') this.closeVoiceFileViewer();
      });
      mount.querySelector('#voice-file-viewer-close')?.addEventListener('click', () => this.closeVoiceFileViewer());
    },

    async _voiceFetchJson(url) {
      const response = await fetch(url, {
        headers: typeof this.authHeaders === 'function' ? this.authHeaders() : {},
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = trimText(body?.detail || body?.message);
        throw new Error(detail || `${response.status} ${response.statusText}`);
      }
      return body;
    },

    async _loadVoiceFolder(path) {
      const data = await this._voiceFetchJson(`/api/files/browse?path=${encodeURIComponent(path)}`);
      this.voiceFileViewer.type = 'folder';
      this.voiceFileViewer.parent = trimText(data.parent || '');
      this.voiceFileViewer.items = Array.isArray(data.items) ? data.items : [];
    },

    async _loadVoiceTextFile(path) {
      const response = await fetch(`/api/files/read?path=${encodeURIComponent(path)}`, {
        headers: typeof this.authHeaders === 'function' ? this.authHeaders() : {},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = trimText(data?.detail || data?.message);
        if (response.status === 413 || /file too large/i.test(detail)) {
          this.voiceFileViewer.type = 'binary';
          this.voiceFileViewer.notice = detail || 'Preview disabled for large files.';
          return;
        }
        if (response.status === 400 && /directory/i.test(detail)) {
          await this._loadVoiceFolder(path);
          return;
        }
        throw new Error(detail || `${response.status} ${response.statusText}`);
      }
      this.voiceFileViewer.content = String(data.content || data.text || '').slice(0, 50000);
      if (typeof hljs !== 'undefined' && this.voiceFileViewer.type === 'code') {
        const lang = this._fileLanguage(path);
        try {
          const result = hljs.highlight(this.voiceFileViewer.content, { language: lang, ignoreIllegals: true });
          this.voiceFileViewer.content = result.value;
        } catch (_) {}
      }
    },

    async openVoiceFileViewer(path, explicitKind = '', options = {}) {
      const normalizedPath = this._normalizeViewerPath(path, explicitKind);
      if (!normalizedPath) return;
      const viewer = this.voiceFileViewer;
      const revealState = this._ensureVoiceFileRevealState();
      const detectedType = this._detectFileType(normalizedPath, explicitKind);
      const alreadyOpen = !!(
        viewer?.open
        && trimText(viewer.path) === normalizedPath
        && trimText(viewer.type) === detectedType
        && !viewer.loading
      );
      if (alreadyOpen) {
        viewer.autoOpened = viewer.autoOpened && !!options.auto;
        return;
      }
      viewer.open = true;
      viewer.path = normalizedPath;
      viewer.type = detectedType;
      viewer.content = '';
      viewer.items = [];
      viewer.parent = '';
      viewer.loading = true;
      viewer.error = '';
      viewer.notice = '';
      viewer.autoOpened = !!options.auto;
      revealState.lastOpenAt = Date.now();
      revealState.lastOpenPath = normalizedPath;
      this._renderFileViewerDOM();

      try {
        if (['pdf', 'image', 'video', 'audio', 'web', 'binary'].includes(viewer.type)) {
          return;
        }
        if (viewer.type === 'folder') {
          await this._loadVoiceFolder(normalizedPath);
          return;
        }
        await this._loadVoiceTextFile(normalizedPath);
      } catch (error) {
        viewer.error = error?.message || 'Failed to load file';
      } finally {
        viewer.loading = false;
        this._renderFileViewerDOM();
      }
    },

    closeVoiceFileViewer() {
      if (this.voiceFileViewer) {
        this.voiceFileViewer.lastManualAt = Date.now();
        this.voiceFileViewer.autoOpened = false;
      }
      this.pauseVoiceFileReveal?.(8000);
      this._resetVoiceFileViewerState();
    },

    voiceFileViewerUrl() {
      const base = `/api/files/open?path=${encodeURIComponent(this.voiceFileViewer.path)}`;
      const token = this.authToken || '';
      return token ? `${base}&token=${encodeURIComponent(token)}` : base;
    },

    voiceFileName() {
      return basename(this.voiceFileViewer.path) || 'Unknown';
    },

    initVoiceFileViewer() {
      document.addEventListener('click', (event) => {
        const surfaceTrigger = event.target.closest('[data-voice-surface]');
        if (surfaceTrigger) {
          event.preventDefault();
          if (this.voiceFileViewer) {
            this.voiceFileViewer.lastManualAt = Date.now();
          }
          this.pauseVoiceFileReveal?.(8000);
          const surface = trimText(surfaceTrigger.getAttribute('data-voice-surface') || '').toLowerCase();
          const path = surfaceTrigger.getAttribute('data-voice-path') || '';
          const kind = surfaceTrigger.getAttribute('data-voice-kind') || '';
          if (surface === 'terminal' || (surface === 'approval' && this.terminal?.approvalRequired)) {
            this.focusVoiceSurfaceSpotlight?.({
              type: 'terminal',
              key: path ? `terminal:${path}` : 'terminal:voice',
              path,
              kind,
              title: 'Live PTY shell',
            });
            return;
          }
          if (surface === 'browser') {
            this.focusVoiceSurfaceSpotlight?.({
              type: 'browser',
              key: path ? `browser:${path}` : 'browser:voice',
              path,
              kind: kind || 'web',
              title: basename(path) || 'Live page',
            });
            return;
          }
        }
        const trigger = event.target.closest('.voice-file-chip[data-voice-path], .voice-operator-deck__surface-card[data-voice-path], .voice-operator-deck__artifact[data-voice-path], .activity-feed__file[data-voice-path], .voice-file-viewer__folder-entry[data-voice-path], .voice-file-viewer__folder-up[data-voice-path]');
        if (trigger) {
          event.preventDefault();
          if (this.voiceFileViewer) {
            this.voiceFileViewer.lastManualAt = Date.now();
          }
          this.pauseVoiceFileReveal?.(8000);
          const path = trigger.getAttribute('data-voice-path') || '';
          const kind = trigger.getAttribute('data-voice-kind') || '';
          if (path) this.openVoiceFileViewer(path, kind, { auto: false });
          return;
        }

        const link = event.target.closest('.voice-response-render a[href]');
        if (link) {
          const href = link.getAttribute('href') || '';
          if (/^https?:\/\//i.test(href)) {
            event.preventDefault();
            if (this.voiceFileViewer) {
              this.voiceFileViewer.lastManualAt = Date.now();
            }
            this.pauseVoiceFileReveal?.(8000);
            this.openVoiceFileViewer(href, 'web', { auto: false });
          }
        }
      });

      window.addEventListener('voice-open-file', (event) => {
        const path = event.detail?.path;
        const kind = event.detail?.kind || '';
        if (path) this.openVoiceFileViewer(path, kind, { auto: false });
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && this.voiceFileViewer?.open) {
          this.closeVoiceFileViewer();
        }
      });
    },
  };
}

window.axonVoiceFileViewerMixin = axonVoiceFileViewerMixin;
