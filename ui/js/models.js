/* ══════════════════════════════════════════════════════════════
   Axon — Model Management Module
   ══════════════════════════════════════════════════════════════ */

function axonModelsMixin() {
  return {

    // ── Model management ────────────────────────────────────────────
    async loadOllamaModels() {
      if (!this.runtimeStatus?.local_models_enabled) {
        this.ollamaModels = [];
        this.ollamaRecommended = [];
        return;
      }
      this.modelsLoading = true;
      try {
        const [modRes, recRes] = await Promise.all([
          this.api('GET', '/api/ollama/models'),
          this.api('GET', '/api/ollama/recommended'),
        ]);
        this.ollamaModels = modRes.models || [];
        this.ollamaRecommended = recRes.models || [];
        this.syncChatModel(this.settingsForm.code_model || this.settingsForm.ollama_model || this.selectedChatModel);
      } catch(e) {
        this.ollamaModels = [];
        this.ollamaRecommended = [];
      }
      this.modelsLoading = false;
    },

    async pullModel(modelName) {
      if (this.modelPullProgress[modelName]) return;
      this.modelPullProgress = {
        ...this.modelPullProgress,
        [modelName]: { status: 'starting', pct: 0, label: 'Starting...' }
      };
      try {
        const resp = await fetch('/api/ollama/pull', {
          method: 'POST',
          headers: this.authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ model: modelName }),
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          throw new Error('Session expired');
        }
        if (!resp.ok) {
          const detail = await resp.text().catch(() => '');
          throw new Error(detail || 'Unable to start model pull');
        }
        const reader = resp.body?.getReader?.();
        if (!reader) throw new Error('No progress stream returned');
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (data.error) throw new Error(data.error);
              const pct = data.total ? Math.round((data.completed || 0) / data.total * 100) : 0;
              this.modelPullProgress = {
                ...this.modelPullProgress,
                [modelName]: {
                  status: data.status || 'pulling',
                  pct,
                  label: data.status === 'success' ? '✓ Done' : (pct > 0 ? `${pct}%` : data.status || '…'),
                }
              };
            } catch(err) {
              if (err instanceof Error && err.message) throw err;
            }
          }
        }
        // Refresh model list
        await this.loadOllamaModels();
        this.modelPullProgress = {
          ...this.modelPullProgress,
          [modelName]: { status: 'done', pct: 100, label: '✓ Installed' }
        };
        this.showToast(`${modelName} installed`);
        setTimeout(() => {
          const next = { ...this.modelPullProgress };
          delete next[modelName];
          this.modelPullProgress = next;
        }, 3000);
      } catch(e) {
        this.modelPullProgress = {
          ...this.modelPullProgress,
          [modelName]: { status: 'error', pct: 0, label: `Error: ${e.message}` }
        };
        this.showToast(`Pull failed: ${e.message}`);
      }
    },

    async pullCustomModel() {
      const modelName = this.customModelName.trim();
      if (!modelName) return;
      await this.pullModel(modelName);
      const status = this.modelPullProgress[modelName]?.status;
      if (status !== 'error') this.customModelName = '';
    },

    async deleteModel(modelName) {
      if (!confirm(`Delete model "${modelName}"? This cannot be undone.`)) return;
      try {
        await this.api('DELETE', `/api/ollama/models/${encodeURIComponent(modelName)}`);
        await this.loadOllamaModels();
        this.syncChatModel();
      } catch(e) {
        alert(`Failed to delete: ${e.message}`);
      }
    },

    updateChatProject() {
      this.chatProject = this.projects.find(p => p.id == this.chatProjectId) || null;
      this._userScrolled = false;
      this.showScrollToBottom = false;
      if (typeof this._refreshWorkspaceEnv === 'function') this._refreshWorkspaceEnv();
      if (typeof this.loadChatHistory === 'function') {
        this.loadChatHistory();
      } else {
        this.$nextTick(() => requestAnimationFrame(() => this.scrollChat?.(true)));
      }
      // Refresh tasks for the newly selected workspace
      if (typeof this.loadWorkspaceTasks === 'function') this.loadWorkspaceTasks();
    },

    clearHistory() {
      this.chatMessages = [];
      this.api('DELETE', '/api/chat/history' + (this.chatProjectId ? `?project_id=${this.chatProjectId}` : ''));
    },

  };
}

window.axonModelsMixin = axonModelsMixin;
