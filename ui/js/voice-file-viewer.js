/* ══════════════════════════════════════════════════════════════
   Axon — Voice File Viewer (Holographic)
   ══════════════════════════════════════════════════════════════ */

function axonVoiceFileViewerMixin() {
  return {
    voiceFileViewer: {
      open: false,
      path: '',
      type: '',       // 'pdf' | 'image' | 'code' | 'text' | 'video' | 'audio'
      content: '',
      loading: false,
      error: '',
    },

    _detectFileType(path) {
      // External URLs → open in holographic iframe
      if (/^https?:\/\//i.test(path)) return 'web';
      const ext = String(path || '').split('.').pop().toLowerCase();
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

    _renderFileViewerDOM() {
      const mount = document.getElementById('voice-file-viewer-mount');
      if (!mount) return;
      const v = this.voiceFileViewer;
      if (!v.open) { mount.innerHTML = ''; return; }

      const url = this.voiceFileViewerUrl();
      const name = this.voiceFileName();
      const esc = (s) => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

      let body = '';
      if (v.loading) {
        body = '<div class="voice-file-viewer__loading"><div class="voice-file-viewer__spinner"></div><span>Loading file…</span></div>';
      } else if (v.error) {
        body = `<div class="voice-file-viewer__error">${esc(v.error)}</div>`;
      } else if (v.type === 'pdf') {
        body = `<iframe src="${esc(url)}" class="voice-file-viewer__iframe"></iframe>`;
      } else if (v.type === 'web') {
        body = `<iframe src="${esc(v.path)}" class="voice-file-viewer__iframe" sandbox="allow-scripts allow-same-origin allow-popups" referrerpolicy="no-referrer"></iframe>`;
      } else if (v.type === 'image') {
        body = `<img src="${esc(url)}" alt="${esc(name)}" class="voice-file-viewer__image">`;
      } else if (v.type === 'video') {
        body = `<video src="${esc(url)}" controls class="voice-file-viewer__video"></video>`;
      } else if (v.type === 'audio') {
        body = `<div class="voice-file-viewer__audio-wrap"><audio src="${esc(url)}" controls style="width:100%"></audio></div>`;
      } else {
        body = `<pre class="voice-file-viewer__code"><code>${v.content || esc('(empty)')}</code></pre>`;
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
                <span class="voice-file-viewer__title">${esc(name)}</span>
              </div>
              <div class="voice-file-viewer__path">${esc(v.path)}</div>
              <button class="voice-file-viewer__close" id="voice-file-viewer-close">✕</button>
            </div>
            <div class="voice-file-viewer__body">${body}</div>
          </div>
        </div>`;

      mount.querySelector('#voice-file-viewer-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'voice-file-viewer-overlay') this.closeVoiceFileViewer();
      });
      mount.querySelector('#voice-file-viewer-close')?.addEventListener('click', () => this.closeVoiceFileViewer());
    },

    async openVoiceFileViewer(path) {
      if (!path) return;
      const v = this.voiceFileViewer;
      v.open = true;
      v.path = path;
      v.type = this._detectFileType(path);
      v.content = '';
      v.loading = true;
      v.error = '';
      this._renderFileViewerDOM();

      // PDF, image, video, audio, web use direct URLs — no content fetch needed
      if (['pdf', 'image', 'video', 'audio', 'web'].includes(v.type)) {
        v.loading = false;
        this._renderFileViewerDOM();
        return;
      }

      // Code/text: fetch content
      try {
        const resp = await fetch(`/api/files/read?path=${encodeURIComponent(path)}`, {
          headers: typeof this.authHeaders === 'function' ? this.authHeaders() : {},
        });
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        const data = await resp.json();
        v.content = String(data.content || data.text || '').slice(0, 50000);
        // Syntax highlight if hljs available
        if (typeof hljs !== 'undefined' && v.type === 'code') {
          const lang = this._fileLanguage(path);
          try {
            const result = hljs.highlight(v.content, { language: lang, ignoreIllegals: true });
            v.content = result.value;
          } catch { /* fallback to plain text */ }
        }
      } catch (err) {
        v.error = err.message || 'Failed to load file';
      } finally {
        v.loading = false;
        this._renderFileViewerDOM();
      }
    },

    closeVoiceFileViewer() {
      this.voiceFileViewer.open = false;
      this.voiceFileViewer.path = '';
      this.voiceFileViewer.content = '';
      this._renderFileViewerDOM();
    },

    voiceFileViewerUrl() {
      const base = `/api/files/open?path=${encodeURIComponent(this.voiceFileViewer.path)}`;
      const token = this.authToken || '';
      return token ? `${base}&token=${encodeURIComponent(token)}` : base;
    },

    voiceFileName() {
      const p = String(this.voiceFileViewer.path || '');
      if (/^https?:\/\//i.test(p)) {
        try { return new URL(p).hostname; } catch { return p.slice(0, 60); }
      }
      const parts = p.split('/');
      return parts[parts.length - 1] || 'Unknown';
    },

    initVoiceFileViewer() {
      document.addEventListener('click', (event) => {
        // Local file chips → holographic viewer
        const trigger = event.target.closest('.voice-file-chip[data-voice-path]');
        if (trigger) {
          event.preventDefault();
          const path = trigger.getAttribute('data-voice-path') || '';
          if (path) this.openVoiceFileViewer(path);
          return;
        }
        // External links inside voice response → holographic iframe
        const link = event.target.closest('.voice-response-render a[href]');
        if (link) {
          const href = link.getAttribute('href') || '';
          if (/^https?:\/\//i.test(href)) {
            event.preventDefault();
            this.openVoiceFileViewer(href);
          }
        }
      });
      // Listen for voice-open-file events from file path chips
      window.addEventListener('voice-open-file', (e) => {
        const path = e.detail?.path;
        if (path) this.openVoiceFileViewer(path);
      });
      // Escape key closes viewer
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.voiceFileViewer?.open) {
          this.closeVoiceFileViewer();
        }
      });
    },
  };
}

window.axonVoiceFileViewerMixin = axonVoiceFileViewerMixin;
