/* ══════════════════════════════════════════════════════════════
   Axon — File Browser Module
   ══════════════════════════════════════════════════════════════ */

function axonFilesMixin() {
  return {

    // ── File browser methods ─────────────────────────────────────
    async loadFiles(path) {
      this.fileLoading = true;
      this.fileViewMode = false;
      try {
        const d = await this.api('GET', `/api/files/browse?path=${encodeURIComponent(path || '~')}`);
        this.filePath = d.path;
        this.fileRelPath = d.rel_path || '';
        if (!this.homeDir) this.homeDir = d.path.replace(d.rel_path, '').replace(/\/$/, '') || d.path;
        // Build breadcrumbs from rel_path
        const parts = (d.rel_path || '').split('/').filter(Boolean);
        this.fileBreadcrumbs = parts;
        this.fileBreadcrumbPaths = parts.map((_, i) => this.homeDir + '/' + parts.slice(0, i + 1).join('/'));
        this.fileItems = d.items;
      } catch(e) {
        this.showToast('Files error: ' + (e.message || e));
      }
      this.fileLoading = false;
    },
    browseUp() {
      const parent = this.filePath.split('/').slice(0, -1).join('/') || '/';
      if (parent && parent !== this.filePath) this.loadFiles(parent);
    },
    async openFile(item) {
      if (item.size > 512 * 1024) { this.showToast('File too large (>512KB)'); return; }
      try {
        const d = await this.api('GET', `/api/files/read?path=${encodeURIComponent(item.path)}`);
        this.fileOpenPath = item.path;
        this.fileOpenName = item.name;
        this.fileContent = d.content;
        this.fileEdited = false;
        this.fileViewMode = true;
      } catch(e) {
        this.showToast('Cannot open: ' + (e.message || e));
      }
    },
    async saveFile() {
      try {
        await this.api('POST', '/api/files/write', { path: this.fileOpenPath, content: this.fileContent });
        this.fileEdited = false;
        this.showToast('Saved ✓');
      } catch(e) {
        this.showToast('Save failed: ' + (e.message || e));
      }
    },
    fileIcon(ext) {
      const map = {
        '.py':'🐍', '.js':'🟨', '.ts':'🔷', '.tsx':'🔷', '.jsx':'🟨',
        '.json':'{}', '.md':'📝', '.txt':'📄', '.sh':'⚙️', '.env':'🔑',
        '.html':'🌐', '.css':'🎨', '.sql':'🗄️', '.yml':'⚙️', '.yaml':'⚙️',
        '.png':'🖼️', '.jpg':'🖼️', '.jpeg':'🖼️', '.gif':'🖼️', '.svg':'🖼️',
        '.zip':'📦', '.tar':'📦', '.gz':'📦', '.pdf':'📕', '.log':'📋',
      };
      return map[ext] || '📄';
    },
    formatBytes(b) {
      if (b < 1024) return b + ' B';
      if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
      return (b/1024/1024).toFixed(1) + ' MB';
    },

    async checkOllamaStatus() {
      try {
        this.ollamaStatus = await this.api('GET', '/api/ollama/status');
        if (this.ollamaStatus?.runtime_mode) {
          this.settingsForm.ollama_runtime_mode = this.ollamaStatus.runtime_mode;
        }
      } catch(e) {
        this.ollamaStatus = { running: false, models: [], url: '', runtime_mode: this.settingsForm.ollama_runtime_mode || 'gpu_default', service_detail: '', service_mode: '' };
      }
    },

    async switchOllamaRuntimeMode(mode) {
      if (this.ollamaRuntimeSwitching) return;
      const target = String(mode || '').toLowerCase();
      if (!['cpu_safe', 'gpu_default'].includes(target)) return;
      this.ollamaRuntimeSwitching = true;
      try {
        const res = await this.api('POST', '/api/ollama/runtime-mode', { mode: target });
        this.settingsForm.ollama_runtime_mode = res.runtime_mode || target;
        this.settingsForm.ollama_url = res.ollama_url || this.settingsForm.ollama_url;
        await this.checkOllamaStatus();
        await this.loadOllamaModels();
        await this.loadRuntimeStatus();
        this.showToast(target === 'cpu_safe' ? 'CPU Safe Mode enabled' : 'GPU Default selected');
      } catch (e) {
        this.showToast(`Runtime switch failed: ${e.message}`);
      }
      this.ollamaRuntimeSwitching = false;
    },

  };
}

window.axonFilesMixin = axonFilesMixin;
