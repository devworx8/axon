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

    async openVoiceFileViewer(path) {
      if (!path) return;
      const v = this.voiceFileViewer;
      v.open = true;
      v.path = path;
      v.type = this._detectFileType(path);
      v.content = '';
      v.loading = true;
      v.error = '';

      // PDF, image, video, audio use direct URLs — no content fetch needed
      if (['pdf', 'image', 'video', 'audio'].includes(v.type)) {
        v.loading = false;
        return;
      }

      // Code/text: fetch content
      try {
        const resp = await fetch(`/api/files/read?path=${encodeURIComponent(path)}`);
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
      }
    },

    closeVoiceFileViewer() {
      this.voiceFileViewer.open = false;
      this.voiceFileViewer.path = '';
      this.voiceFileViewer.content = '';
    },

    voiceFileViewerUrl() {
      return `/api/files/open?path=${encodeURIComponent(this.voiceFileViewer.path)}`;
    },

    voiceFileName() {
      const parts = String(this.voiceFileViewer.path || '').split('/');
      return parts[parts.length - 1] || 'Unknown';
    },

    initVoiceFileViewer() {
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
