/* ══════════════════════════════════════════════════════════════
   Axon — Resources Module
   ══════════════════════════════════════════════════════════════ */

const AXON_STARTER_PLAYBOOKS_PATH = '/js/playbook-starters.json';

function axonNormalizeStarterPlaybook(item = {}) {
  const key = String(item?.key || '').trim().toLowerCase();
  if (!key) return null;
  const title = String(item?.title || '').trim();
  const content = String(item?.content || '').trim();
  if (!title || !content) return null;
  return {
    id: `starter:${key}`,
    title,
    content,
    tags: String(item?.tags || '').trim(),
    project_id: null,
    project_name: '',
    pinned: 0,
    used_count: 0,
    meta: {
      starter: true,
      starter_key: key,
      starter_group: String(item?.group || 'starter-pack').trim() || 'starter-pack',
    },
  };
}

function axonResourcesMixin() {
  return {

    get filteredResources() {
      const search = (this.resourceSearch || '').toLowerCase().trim();
      const kind = (this.resourceKindFilter || '').toLowerCase();
      const source = (this.resourceSourceFilter || '').toLowerCase();
      const status = (this.resourceStatusFilter || '').toLowerCase();
      return (this.resources || []).filter(resource => {
        const matchesSearch = !search || [
          resource.title,
          resource.source_url,
          resource.mime_type,
          resource.preview_text,
        ].some(value => String(value || '').toLowerCase().includes(search));
        const matchesKind = !kind || String(resource.kind || '').toLowerCase() === kind;
        const matchesSource = !source || String(resource.source_type || '').toLowerCase() === source;
        const matchesStatus = !status || String(resource.status || '').toLowerCase() === status;
        return matchesSearch && matchesKind && matchesSource && matchesStatus;
      });
    },

    get filteredPrompts() {
      const q = (this.promptSearch || '').toLowerCase().trim();
      if (!q) return this.prompts;
      return this.prompts.filter(p =>
        p.title.toLowerCase().includes(q) ||
        (p.tags || '').toLowerCase().includes(q) ||
        (p.project_name || '').toLowerCase().includes(q)
      );
    },

    promptIsComposerPreset(pr) {
      return (pr?.meta?.preset_type || '') === 'composer';
    },

    promptIsStarter(pr) {
      return !!pr?.meta?.starter;
    },

    composerPresetPayload(includeResources = true, includeResearchPack = true) {
      const options = this.normalizedComposerOptions();
      const researchPack = includeResearchPack ? this.currentResearchPack() : null;
      return {
        preset_type: 'composer',
        composer_options: options,
        resource_ids: includeResources ? this.selectedResources.map(resource => Number(resource.id)).filter(Boolean) : [],
        research_pack_id: researchPack ? Number(researchPack.id) : null,
        research_pack_title: researchPack?.title || '',
      };
    },

    prefillPlaybookFromComposer() {
      this.newPrompt = {
        title: '',
        content: this.chatInput || '',
        project_id: this.chatProjectId || '',
        tags: 'composer,preset',
        save_composer_preset: true,
        include_selected_resources: true,
        include_selected_research_pack: true,
      };
      this.switchTab('prompts');
      this.showAddPrompt = true;
      this.showComposerMenu = false;
      this.showToast('Composer setup copied into a new playbook draft');
    },

    async loadStarterPlaybooks(force = false) {
      if (!force && Array.isArray(this._starterPlaybooksCache) && this._starterPlaybooksCache.length) {
        return this._starterPlaybooksCache;
      }
      try {
        const response = await fetch(AXON_STARTER_PLAYBOOKS_PATH, { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        const items = Array.isArray(payload?.items) ? payload.items : [];
        this._starterPlaybooksCache = items
          .map(axonNormalizeStarterPlaybook)
          .filter(Boolean);
      } catch (_) {
        this._starterPlaybooksCache = [];
      }
      return this._starterPlaybooksCache;
    },

    mergeStarterPlaybooks(prompts = [], starters = []) {
      const rows = Array.isArray(prompts) ? prompts : [];
      const starterRows = Array.isArray(starters) ? starters : [];
      const existingKeys = new Set(
        rows
          .map(prompt => String(prompt?.meta?.starter_key || '').trim().toLowerCase())
          .filter(Boolean)
      );
      const existingTitles = new Set(
        rows
          .map(prompt => String(prompt?.title || '').trim().toLowerCase())
          .filter(Boolean)
      );
      const missingStarters = starterRows.filter((starter) => {
        const key = String(starter?.meta?.starter_key || '').trim().toLowerCase();
        const title = String(starter?.title || '').trim().toLowerCase();
        if (key && existingKeys.has(key)) return false;
        if (title && existingTitles.has(title)) return false;
        return true;
      });
      return [...rows, ...missingStarters];
    },

    async seedStarterPlaybook(kind = 'code-review') {
      const starters = await this.loadStarterPlaybooks();
      const normalizedKind = String(kind || '').trim().toLowerCase();
      const preset = starters.find(item => item?.meta?.starter_key === normalizedKind) || starters[0];
      if (!preset) {
        this.showToast('Starter playbook pack is unavailable');
        return;
      }
      this.newPrompt = {
        ...this.newPrompt,
        title: preset.title,
        content: preset.content,
        tags: preset.tags,
      };
      this.showAddPrompt = true;
      this.showToast('Starter playbook loaded');
    },

    async applyPromptPreset(pr, { showToast = true } = {}) {
      const meta = pr?.meta || {};
      if (!this.promptIsComposerPreset(pr)) return;
      this.composerOptions = {
        ...this.composerOptions,
        ...(meta.composer_options || {}),
      };
      const resourceIds = Array.isArray(meta.resource_ids) ? meta.resource_ids.map(Number).filter(Boolean) : [];
      if (resourceIds.length) {
        if (!this.resources.length) await this.loadResources();
        const matched = this.resources.filter(resource => resourceIds.includes(Number(resource.id)));
        this.mergeSelectedResources(matched);
      }
      if (meta.research_pack_id) {
        if (!this.researchPacks.length) await this.loadResearchPacks(meta.research_pack_id);
        else this.selectedResearchPackId = Number(meta.research_pack_id);
      }
      if (showToast) this.showToast('Composer preset loaded');
    },

    async loadPrompts() {
      try {
        const [rows, starters] = await Promise.all([
          this.api('GET', '/api/prompts'),
          this.loadStarterPlaybooks(),
        ]);
        this.prompts = this.mergeStarterPlaybooks(rows || [], starters || []);
      } catch(e) { this.showToast('Failed to load playbooks'); }
    },

    async savePrompt() {
      if (!this.newPrompt.title || !this.newPrompt.content) return;
      try {
        const meta = this.newPrompt.save_composer_preset
          ? this.composerPresetPayload(
              this.newPrompt.include_selected_resources,
              this.newPrompt.include_selected_research_pack,
            )
          : {};
        await this.api('POST', '/api/prompts', {
          title: this.newPrompt.title,
          content: this.newPrompt.content,
          tags: this.newPrompt.tags,
          project_id: this.newPrompt.project_id ? parseInt(this.newPrompt.project_id) : null,
          meta,
        });
        await this.loadPrompts();
        this.showAddPrompt = false;
        this.resetNewPrompt();
        this.showToast('Playbook saved');
      } catch(e) { this.showToast('Failed'); }
    },

    async enhancePrompt() {
      try {
        const projectCtx = this.newPrompt.project_id
          ? this.projects.find(p => p.id == this.newPrompt.project_id)?.name
          : null;
        const res = await this.api('POST', '/api/prompts/enhance', {
          content: this.newPrompt.content,
          project_context: projectCtx,
        });
        this.newPrompt.content = res.enhanced;
        this.showToast('Playbook refined ✨');
      } catch(e) { this.showToast('Error: ' + e.message); }
    },

    async copyPrompt(pr) {
      await navigator.clipboard.writeText(pr.content);
      if (!this.promptIsStarter(pr)) this.api('GET', '/api/prompts');
      this.showToast('Copied to clipboard');
    },

    async sendPromptToChat(pr) {
      if (this.promptIsComposerPreset(pr)) {
        await this.applyPromptPreset(pr, { showToast: false });
      }
      this.chatInput = pr.content;
      this.switchTab('chat');
      this.showToast(this.promptIsComposerPreset(pr) ? 'Preset loaded into Console' : 'Playbook sent to Console');
    },

    async deletePrompt(id) {
      if (String(id || '').startsWith('starter:')) {
        this.showToast('Starter playbooks stay read-only. Save a copy if you want to customize one.');
        return;
      }
      if (!confirm('Delete this playbook?')) return;
      await this.api('DELETE', `/api/prompts/${id}`);
      this.prompts = this.prompts.filter(p => p.id !== id);
    },

    resetNewPrompt() {
      this.newPrompt = {
        title:'', content:'', project_id:'', tags:'',
        save_composer_preset: false,
        include_selected_resources: true,
        include_selected_research_pack: true,
      };
    },

    openPrompt(pr) {
      this.promptModal.open = true;
      this.promptModal.editing = false;
      this.promptModal.prompt = pr;
    },

    async savePromptEdit() {
      try {
        if (this.promptIsStarter(this.promptModal.prompt)) {
          const created = await this.api('POST', '/api/prompts', {
            title: this.promptModal.editTitle,
            content: this.promptModal.editContent,
            tags: this.promptModal.editTags,
            project_id: null,
            meta: {},
          });
          await this.loadPrompts();
          this.promptModal.prompt = created;
          this.promptModal.editing = false;
          this.showToast('Starter playbook copied into your library');
          return;
        }
        const updated = await this.api('PATCH', `/api/prompts/${this.promptModal.prompt.id}`, {
          title: this.promptModal.editTitle,
          content: this.promptModal.editContent,
          tags: this.promptModal.editTags,
        });
        // Update in list
        const idx = this.prompts.findIndex(p => p.id === this.promptModal.prompt.id);
        if (idx !== -1) this.prompts[idx] = { ...this.prompts[idx], ...updated };
        this.promptModal.prompt = this.prompts[idx];
        this.promptModal.editing = false;
        this.showToast('Saved ✓');
      } catch(e) { this.showToast('Save failed: ' + e.message); }
    },

    async togglePin(pr) {
      if (!pr) return;
      if (this.promptIsStarter(pr)) {
        this.showToast('Starter playbooks stay read-only. Save a copy first if you want to pin one.');
        return;
      }
      const res = await this.api('POST', `/api/prompts/${pr.id}/pin`);
      // Update in list and modal
      const idx = this.prompts.findIndex(p => p.id === pr.id);
      if (idx !== -1) this.prompts[idx] = { ...this.prompts[idx], pinned: res.pinned ? 1 : 0 };
      if (this.promptModal.prompt?.id === pr.id) {
        this.promptModal.prompt = this.prompts[idx];
      }
      this.showToast(res.pinned ? '📌 Pinned' : 'Unpinned');
      // Re-sort: pinned first
      this.prompts = [...this.prompts].sort((a, b) => (b.pinned || 0) - (a.pinned || 0));
    },

    async loadResearchPacks(selectId = null) {
      this.researchPacksLoading = true;
      try {
        const data = await this.api('GET', '/api/research-packs?include_resources=true');
        this.researchPacks = data.items || [];
        if (selectId) this.selectedResearchPackId = Number(selectId);
        else if (this.selectedResearchPackId && !this.researchPacks.some(pack => Number(pack.id) === Number(this.selectedResearchPackId))) this.selectedResearchPackId = null;
      } catch(e) {
        this.showToast(`Research packs error: ${e.message}`);
      }
      this.researchPacksLoading = false;
    },

    async createResearchPack() {
      const title = (this.newResearchPack.title || '').trim();
      if (!title) return;
      try {
        const pack = await this.api('POST', '/api/research-packs', {
          title,
          description: this.newResearchPack.description || '',
          pinned: !!this.newResearchPack.pinned,
        });
        await this.loadResearchPacks(pack.id);
        this.newResearchPack = { title: '', description: '', pinned: false };
        this.showAddResearchPack = false;
        this.showToast('Research pack created');
      } catch(e) {
        this.showToast(`Create failed: ${e.message}`);
      }
    },

    async addResourceToSelectedPack(resource) {
      const pack = this.currentResearchPack();
      if (!pack) {
        this.showToast('Select a research pack first');
        return;
      }
      try {
        const updated = await this.api('POST', `/api/research-packs/${pack.id}/items`, {
          resource_ids: [Number(resource.id)],
        });
        const idx = this.researchPacks.findIndex(item => Number(item.id) === Number(pack.id));
        if (idx !== -1) this.researchPacks[idx] = updated;
        this.selectedResearchPackId = Number(updated.id);
        this.showToast('Added to research pack');
      } catch(e) {
        this.showToast(`Pack update failed: ${e.message}`);
      }
    },

    resourceInSelectedPack(resourceId) {
      const pack = this.currentResearchPack();
      if (!pack) return false;
      return (pack.resources || []).some(resource => Number(resource.id) === Number(resourceId));
    },

    async removePackResource(packId, resourceId) {
      try {
        const updated = await this.api('DELETE', `/api/research-packs/${packId}/items/${resourceId}`);
        const idx = this.researchPacks.findIndex(item => Number(item.id) === Number(packId));
        if (idx !== -1) this.researchPacks[idx] = updated;
        this.showToast('Removed from research pack');
      } catch(e) {
        this.showToast(`Remove failed: ${e.message}`);
      }
    },

    async toggleResearchPackPin(pack) {
      try {
        const updated = await this.api('PATCH', `/api/research-packs/${pack.id}`, {
          pinned: !pack.pinned,
        });
        const idx = this.researchPacks.findIndex(item => Number(item.id) === Number(pack.id));
        if (idx !== -1) this.researchPacks[idx] = updated;
        this.researchPacks = [...this.researchPacks].sort((a, b) => (Number(b.pinned) - Number(a.pinned)));
      } catch(e) {
        this.showToast(`Pin failed: ${e.message}`);
      }
    },

    useResearchPack(pack) {
      this.selectedResearchPackId = Number(pack.id);
      this.showComposerMenu = false;
      this.switchTab('chat');
      this.showToast(`Research Pack ready: ${pack.title}`);
    },

    clearResearchPack() {
      this.selectedResearchPackId = null;
      this.showToast('Research Pack cleared');
    },

    async deleteResearchPack(pack) {
      if (!confirm(`Delete research pack "${pack.title}"?`)) return;
      try {
        await this.api('DELETE', `/api/research-packs/${pack.id}`);
        this.researchPacks = this.researchPacks.filter(item => Number(item.id) !== Number(pack.id));
        if (Number(this.selectedResearchPackId) === Number(pack.id)) this.selectedResearchPackId = null;
        this.showToast('Research pack deleted');
      } catch(e) {
        this.showToast(`Delete failed: ${e.message}`);
      }
    },

    async loadMemoryItems() {
      this.memoryLoading = true;
      try {
        const data = await this.api('GET', '/api/memory/items?limit=180');
        this.memoryItems = data.items || [];
      } catch(e) {
        this.showToast(`Memory error: ${e.message}`);
      }
      this.memoryLoading = false;
    },

    async setMemoryPinned(item, value) {
      try {
        const updated = await this.api('PATCH', `/api/memory/items/${item.id}`, { pinned: !!value });
        const idx = this.memoryItems.findIndex(entry => Number(entry.id) === Number(item.id));
        if (idx !== -1) this.memoryItems[idx] = updated;
      } catch(e) {
        this.showToast(`Pin failed: ${e.message}`);
      }
    },

    async setMemoryTrust(item, value) {
      try {
        const updated = await this.api('PATCH', `/api/memory/items/${item.id}`, { trust_level: value });
        const idx = this.memoryItems.findIndex(entry => Number(entry.id) === Number(item.id));
        if (idx !== -1) this.memoryItems[idx] = updated;
      } catch(e) {
        this.showToast(`Trust update failed: ${e.message}`);
      }
    },

  };
}

window.axonResourcesMixin = axonResourcesMixin;
