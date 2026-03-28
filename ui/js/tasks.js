/* ══════════════════════════════════════════════════════════════
   Axon — Tasks Module
   ══════════════════════════════════════════════════════════════ */

function axonTasksMixin() {
  return {

    async loadTasks() {
      this.tasksLoading = true;
      try {
        this.tasks = await this.api('GET', '/api/tasks?status=');
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
        t.status = 'done';
        this.urgentCount = this.tasks.filter(t => t.priority === 'urgent' || t.priority === 'high').length;
        this.showToast('Mission completed ✓');
      } catch(e) { this.showToast('Failed'); }
    },

    async setTaskStatus(t, status) {
      try {
        await this.api('PATCH', `/api/tasks/${t.id}`, { status });
        t.status = status;
        this.urgentCount = this.tasks.filter(t => t.priority === 'urgent' || t.priority === 'high').length;
        this.showToast(`Mission → ${this.taskStatusLabel(status)}`);
      } catch(e) { this.showToast('Failed'); }
    },

    async saveTaskEdit(t) {
      try {
        await this.api('PATCH', `/api/tasks/${t.id}`, {
          title: t.title,
          detail: t.detail,
          priority: t.priority,
          due_date: t.due_date || null,
        });
        this.editingTaskId = null;
        this.showToast('Mission updated');
      } catch(e) { this.showToast('Failed: ' + e.message); }
    },

    async deleteTask(t) {
      if (!confirm(`Delete mission "${t.title}"?`)) return;
      try {
        await this.api('DELETE', `/api/tasks/${t.id}`);
        this.tasks = this.tasks.filter(x => x.id !== t.id);
        this.urgentCount = this.tasks.filter(t => t.priority === 'urgent' || t.priority === 'high').length;
        this.showToast('Mission deleted');
      } catch(e) { this.showToast('Failed: ' + e.message); }
    },

    runMission(t) {
      const prompt = t.detail
        ? `${t.title}\n\nDetails: ${t.detail}`
        : t.title;
      this.switchTab('chat');
      this.$nextTick(() => {
        this.chatInput = prompt;
        this.$nextTick(() => this.sendChat());
      });
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

    taskStatusLabel(status) {
      const map = {
        open: 'Pending',
        in_progress: 'In progress',
        done: 'Done',
        cancelled: 'Blocked',
      };
      return map[String(status || 'open')] || 'Pending';
    },

    taskStatusClass(status) {
      const key = String(status || 'open');
      if (key === 'done') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
      if (key === 'in_progress') return 'border-blue-500/20 bg-blue-500/10 text-blue-300';
      if (key === 'cancelled') return 'border-rose-500/20 bg-rose-500/10 text-rose-300';
      return 'border-slate-700 bg-slate-800/70 text-slate-300';
    },

    missionProgressValue(status) {
      const key = String(status || 'open');
      if (key === 'done') return 100;
      if (key === 'in_progress') return 60;
      if (key === 'cancelled') return 100;
      return 20;
    },

    missionSummaryText() {
      const items = this.tasks || [];
      const active = items.filter(t => t.status === 'in_progress').length;
      const blocked = items.filter(t => t.status === 'cancelled').length;
      const done = items.filter(t => t.status === 'done').length;
      return `${active} active · ${blocked} blocked · ${done} done`;
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
