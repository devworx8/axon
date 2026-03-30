/* ══════════════════════════════════════════════════════════════
   Axon — Resources Module
   ══════════════════════════════════════════════════════════════ */

function axonResourcesMixin() {
  return {

    // ── Resource categorisation ────────────────────────────
    _resourceCategoryRules: [
      { id: 'python',       label: 'Python',             icon: '🐍', color: 'blue',    keywords: ['python', 'pep 8', 'pep 20', 'mypy', 'type hint', 'pytest'] },
      { id: 'js-ts',        label: 'JavaScript / TypeScript', icon: '🟨', color: 'amber',  keywords: ['javascript', 'typescript', 'airbnb', 'clean code typescript', 'ts deep dive'] },
      { id: 'react',        label: 'React',              icon: '⚛️', color: 'cyan',    keywords: ['react', 'hooks', 'managing state', 'thinking in react'] },
      { id: 'nextjs',       label: 'Next.js',            icon: '▲',  color: 'slate',   keywords: ['next.js', 'nextjs', 'app router'] },
      { id: 'fastapi',      label: 'FastAPI',            icon: '⚡', color: 'emerald', keywords: ['fastapi'] },
      { id: 'supabase',     label: 'Supabase',           icon: '🟩', color: 'green',   keywords: ['supabase'] },
      { id: 'security',     label: 'Security (OWASP)',   icon: '🛡️', color: 'rose',    keywords: ['owasp', 'csrf', 'sql injection', 'authentication cheat', 'input validation'] },
      { id: 'git',          label: 'Git & Commits',      icon: '🔀', color: 'violet',  keywords: ['git', 'conventional commit'] },
      { id: 'testing',      label: 'Testing',            icon: '🧪', color: 'sky',     keywords: ['testing library', 'pytest', 'test'] },
      { id: 'architecture', label: 'Architecture',       icon: '🏗️', color: 'indigo',  keywords: ['clean architecture', 'architecture'] },
      { id: 'api-design',   label: 'API Design',         icon: '📡', color: 'orange',  keywords: ['rest api', 'json:api', 'api guideline'] },
      { id: 'nodejs',       label: 'Node.js',            icon: '🟢', color: 'lime',    keywords: ['node.js', 'nodejs'] },
      { id: 'shell',        label: 'Shell / Bash',       icon: '💻', color: 'zinc',    keywords: ['bash', 'shell'] },
    ],

    resourceCategory(resource) {
      const title = (resource?.title || '').toLowerCase();
      for (const cat of this._resourceCategoryRules) {
        if (cat.keywords.some(kw => title.includes(kw))) return cat;
      }
      return { id: 'other', label: 'Other', icon: '📦', color: 'slate', keywords: [] };
    },

    get categorizedResources() {
      const cats = {};
      for (const r of this.filteredResources) {
        const cat = this.resourceCategory(r);
        if (!cats[cat.id]) cats[cat.id] = { ...cat, resources: [] };
        cats[cat.id].resources.push(r);
      }
      // Sort: categories with most items first
      return Object.values(cats).sort((a, b) => b.resources.length - a.resources.length);
    },

    resourceCategoryColorClasses(color) {
      const map = {
        blue:    'border-blue-500/25 bg-blue-500/5 text-blue-300',
        amber:   'border-amber-500/25 bg-amber-500/5 text-amber-300',
        cyan:    'border-cyan-500/25 bg-cyan-500/5 text-cyan-300',
        slate:   'border-slate-600/30 bg-slate-700/10 text-slate-300',
        emerald: 'border-emerald-500/25 bg-emerald-500/5 text-emerald-300',
        green:   'border-green-500/25 bg-green-500/5 text-green-300',
        rose:    'border-rose-500/25 bg-rose-500/5 text-rose-300',
        violet:  'border-violet-500/25 bg-violet-500/5 text-violet-300',
        sky:     'border-sky-500/25 bg-sky-500/5 text-sky-300',
        indigo:  'border-indigo-500/25 bg-indigo-500/5 text-indigo-300',
        orange:  'border-orange-500/25 bg-orange-500/5 text-orange-300',
        lime:    'border-lime-500/25 bg-lime-500/5 text-lime-300',
        zinc:    'border-zinc-500/25 bg-zinc-500/5 text-zinc-300',
      };
      return map[color] || map.slate;
    },

    resourceCategoryBadge(color) {
      const map = {
        blue:    'bg-blue-500/15 text-blue-300 border-blue-500/20',
        amber:   'bg-amber-500/15 text-amber-300 border-amber-500/20',
        cyan:    'bg-cyan-500/15 text-cyan-300 border-cyan-500/20',
        slate:   'bg-slate-600/15 text-slate-300 border-slate-600/20',
        emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
        green:   'bg-green-500/15 text-green-300 border-green-500/20',
        rose:    'bg-rose-500/15 text-rose-300 border-rose-500/20',
        violet:  'bg-violet-500/15 text-violet-300 border-violet-500/20',
        sky:     'bg-sky-500/15 text-sky-300 border-sky-500/20',
        indigo:  'bg-indigo-500/15 text-indigo-300 border-indigo-500/20',
        orange:  'bg-orange-500/15 text-orange-300 border-orange-500/20',
        lime:    'bg-lime-500/15 text-lime-300 border-lime-500/20',
        zinc:    'bg-zinc-500/15 text-zinc-300 border-zinc-500/20',
      };
      return map[color] || map.slate;
    },

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

    seedStarterPlaybook(kind = 'code-review') {
      const starters = {
        'code-review': {
          title: 'Code review',
          tags: 'review,quality',
          content: 'Review the current workspace changes with a code review mindset. Focus on bugs, regressions, risks, and missing tests. List findings first in severity order with file references, then open questions, then a short summary.',
        },
        'write-tests': {
          title: 'Write tests',
          tags: 'tests,quality',
          content: 'Inspect the current feature or module and add the smallest high-value automated tests that cover the main behavior, edge cases, and regressions. Keep test style consistent with the repo.',
        },
        'summarise-workspace': {
          title: 'Summarise workspace',
          tags: 'summary,workspace',
          content: 'Scan the current workspace and produce a concise technical summary: architecture, key modules, active risks, recent changes, and recommended next steps.',
        },
      };
      const preset = starters[kind] || starters['code-review'];
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
        const result = await this.api('GET', '/api/prompts');
        this.prompts = result;
      } catch(e) {
        console.error('[Axon] loadPrompts() error:', e);
        this.showToast('Failed to load playbooks');
      }
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
      this.api('POST', `/api/prompts/${pr.id}/use`);
      pr.used_count = (pr.used_count || 0) + 1;
      this.showToast('Copied to clipboard');
    },

    async sendPromptToChat(pr) {
      if (this.promptIsComposerPreset(pr)) {
        await this.applyPromptPreset(pr, { showToast: false });
      }
      this.chatInput = pr.content;
      this.activeTab = 'chat';
      this.api('POST', `/api/prompts/${pr.id}/use`);
      pr.used_count = (pr.used_count || 0) + 1;
      this.showToast(this.promptIsComposerPreset(pr) ? 'Preset loaded into Console' : 'Playbook sent to Console');
    },

    async deletePrompt(id) {
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
