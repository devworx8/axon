/* ══════════════════════════════════════════════════════════════
   Axon — Voice File Viewer (Holographic)
   ══════════════════════════════════════════════════════════════ */

function axonVoiceFileViewerMixin() {
  const escapeHtml = (value = '') => String(value || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const trimText = (value = '') => String(value || '').trim();
  const basename = (value = '') => {
    const raw = trimText(value).replace(/\/+$/, '');
    if (!raw) return '';
    if (/^https?:\/\//i.test(raw)) {
      try { return new URL(raw).hostname; } catch (_) { return raw; }
    }
    const parts = raw.split('/');
    return parts[parts.length - 1] || raw;
  };

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
    },

    _detectFileType(path, explicitKind = '') {
      const forced = trimText(explicitKind).toLowerCase();
      if (forced) return forced;
      if (/^https?:\/\//i.test(path)) return 'web';
      const raw = trimText(path).replace(/\/+$/, '');
      const ext = raw.split('.').pop().toLowerCase();
      if (!ext || ext === raw.toLowerCase()) return 'folder';
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
      return items.map(item => {
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

    async openVoiceFileViewer(path, explicitKind = '') {
      if (!path) return;
      const viewer = this.voiceFileViewer;
      viewer.open = true;
      viewer.path = path;
      viewer.type = this._detectFileType(path, explicitKind);
      viewer.content = '';
      viewer.items = [];
      viewer.parent = '';
      viewer.loading = true;
      viewer.error = '';
      this._renderFileViewerDOM();

      try {
        if (['pdf', 'image', 'video', 'audio', 'web'].includes(viewer.type)) {
          return;
        }
        if (viewer.type === 'folder') {
          await this._loadVoiceFolder(path);
          return;
        }
        await this._loadVoiceTextFile(path);
      } catch (error) {
        viewer.error = error?.message || 'Failed to load file';
      } finally {
        viewer.loading = false;
        this._renderFileViewerDOM();
      }
    },

    closeVoiceFileViewer() {
      this.voiceFileViewer.open = false;
      this.voiceFileViewer.path = '';
      this.voiceFileViewer.content = '';
      this.voiceFileViewer.items = [];
      this.voiceFileViewer.parent = '';
      this._renderFileViewerDOM();
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
        const trigger = event.target.closest('.voice-file-chip[data-voice-path], .voice-operator-deck__surface-card[data-voice-path], .voice-operator-deck__artifact[data-voice-path], .activity-feed__file[data-voice-path], .voice-file-viewer__folder-entry[data-voice-path], .voice-file-viewer__folder-up[data-voice-path]');
        if (trigger) {
          event.preventDefault();
          const path = trigger.getAttribute('data-voice-path') || '';
          const kind = trigger.getAttribute('data-voice-kind') || '';
          if (path) this.openVoiceFileViewer(path, kind);
          return;
        }

        const link = event.target.closest('.voice-response-render a[href]');
        if (link) {
          const href = link.getAttribute('href') || '';
          if (/^https?:\/\//i.test(href)) {
            event.preventDefault();
            this.openVoiceFileViewer(href, 'web');
          }
        }
      });

      window.addEventListener('voice-open-file', (event) => {
        const path = event.detail?.path;
        const kind = event.detail?.kind || '';
        if (path) this.openVoiceFileViewer(path, kind);
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
