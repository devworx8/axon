/* ══════════════════════════════════════════════════════════════
   Axon — Tasks Module
   ══════════════════════════════════════════════════════════════ */

function axonTasksMixin() {
  return {

    async loadTasks() {
      this.tasksLoading = true;
      try {
        this.tasks = await this.api('GET', '/api/tasks?status=open');
        this.urgentCount = this.tasks.filter(t => t.priority === 'urgent' || t.priority === 'high').length;
      } catch(e) { this.showToast('Failed to load missions'); }
      this.tasksLoading = false;
    },

    async addTask() {
      if (!this.newTask.title.trim()) return;
      try {
        await this.api('POST', '/api/tasks', {
          ...this.newTask,
          project_id: this.newTask.project_id ? parseInt(this.newTask.project_id) : null,
        });
        await this.loadTasks();
        this.showAddTask = false;
        this.resetNewTask();
        this.showToast('Mission created');
      } catch(e) { this.showToast('Failed: ' + e.message); }
    },

    async completeTask(t) {
      try {
        await this.api('PATCH', `/api/tasks/${t.id}`, { status: 'done' });
        this.tasks = this.tasks.filter(x => x.id !== t.id);
        this.urgentCount = this.tasks.filter(t => t.priority === 'urgent' || t.priority === 'high').length;
        this.showToast('Mission completed');
      } catch(e) { this.showToast('Failed'); }
    },

    async getSuggestions() {
      try {
        const res = await this.api('POST', '/api/tasks/suggest');
        this.suggestions = res.suggestions;
      } catch(e) { this.showToast('Error: ' + e.message); }
    },

    async acceptSuggestion(s, i) {
      const projectId = s.project_name
        ? (this.projects.find(p => p.name === s.project_name)?.id || null)
        : null;
      try {
        await this.api('POST', '/api/tasks', {
          title: s.title,
          project_id: projectId,
          priority: s.priority,
          detail: s.rationale,
        });
        this.suggestions.splice(i, 1);
        await this.loadTasks();
        this.showToast('Mission created from suggestion');
      } catch(e) { this.showToast('Failed'); }
    },

    resetNewTask() {
      this.newTask = { title:'', detail:'', priority:'medium', project_id:'', due_date:'' };
    },

    currentResearchPack() {
      return (this.researchPacks || []).find(pack => Number(pack.id) === Number(this.selectedResearchPackId)) || null;
    },

    mergeUniqueResources(items = []) {
      const next = [];
      for (const item of items || []) {
        const id = Number(item?.id);
        if (!id || next.some(existing => Number(existing.id) === id)) continue;
        next.push(item);
      }
      return next;
    },

    get filteredResearchPacks() {
      return this.researchPacks || [];
    },

    get filteredMemoryItems() {
      const q = (this.memorySearch || '').toLowerCase().trim();
      const layer = (this.memoryLayerFilter || '').toLowerCase();
      const trust = (this.memoryTrustFilter || '').toLowerCase();
      return (this.memoryItems || []).filter(item => {
        const matchesSearch = !q || [
          item.title,
          item.summary,
          item.source,
          item.workspace_name,
        ].some(value => String(value || '').toLowerCase().includes(q));
        const matchesLayer = !layer || String(item.layer || '').toLowerCase() === layer;
        const matchesTrust = !trust || String(item.trust_level || '').toLowerCase() === trust;
        const matchesPinned = !this.memoryPinnedOnly || !!item.pinned;
        return matchesSearch && matchesLayer && matchesTrust && matchesPinned;
      });
    },

  };
}

window.axonTasksMixin = axonTasksMixin;
