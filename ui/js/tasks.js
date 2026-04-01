/* ══════════════════════════════════════════════════════════════
   Axon — Tasks Module
   ══════════════════════════════════════════════════════════════ */

function axonTasksMixin() {
  return {

    async loadTasks() {
      this.tasksLoading = true;
      try {
        const [tasks, sandboxState] = await Promise.all([
          this.api('GET', '/api/tasks?status='),
          this.api('GET', '/api/tasks/sandboxes').catch(() => ({ sandboxes: [] })),
        ]);
        this.tasks = this.mergeTaskSandboxes(tasks, sandboxState?.sandboxes || []);
        this.urgentCount = this.tasks.filter(t => t.priority === 'urgent' || t.priority === 'high').length;
      } catch(e) { this.showToast('Failed to load missions'); }
      this.tasksLoading = false;
    },

    mergeTaskSandboxes(tasks = [], sandboxes = []) {
      const byTaskId = new Map((sandboxes || []).map(item => [Number(item.task_id), item]));
      return (tasks || []).map(task => ({
        ...task,
        sandbox: byTaskId.get(Number(task.id)) || null,
      }));
    },

    updateTaskSandboxRecord(taskId, sandbox) {
      const id = Number(taskId);
      this.tasks = (this.tasks || []).map(task => (
        Number(task.id) === id
          ? { ...task, sandbox: sandbox ? { ...sandbox } : null }
          : task
      ));
      if (this.taskSandboxReview?.open && Number(this.taskSandboxReview?.task?.id) === id) {
        this.taskSandboxReview.sandbox = sandbox ? { ...sandbox } : null;
      }
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

    async runMissionInSandbox(t, resume = false) {
      if (!t?.project_id) {
        this.showToast('Attach this mission to a workspace before using a sandbox');
        return;
      }
      try {
        const endpoint = resume
          ? `/api/tasks/${t.id}/sandbox/continue`
          : `/api/tasks/${t.id}/sandbox/run`;
        const res = await this.api('POST', endpoint, this.currentSandboxRuntimePayload());
        if (res?.sandbox) {
          this.updateTaskSandboxRecord(
            t.id,
            res.already_running
              ? res.sandbox
              : { ...res.sandbox, status: 'running', last_error: '' },
          );
        }
        if (!resume && t.status === 'open') t.status = 'in_progress';
        if (res?.already_running) {
          this.showToast('Sandbox run already in progress');
        } else {
          this.showToast(resume ? 'Sandbox run resumed' : 'Sandbox run started');
        }
      } catch (e) {
        this.showToast(`Sandbox error: ${e.message}`);
      }
    },

    currentSandboxRuntimePayload() {
      const backend = String(this.settingsForm?.ai_backend || this.runtimeStatus?.backend || 'api').toLowerCase();
      const payload = { backend };
      if (backend === 'api') {
        payload.api_provider = this.settingsForm?.api_provider
          || this.runtimeStatus?.selected_api_provider?.provider_id
          || 'deepseek';
        payload.api_model = (typeof this.selectedApiProviderModel === 'function'
          ? this.selectedApiProviderModel()
          : '') || this.runtimeStatus?.selected_api_provider?.api_model || '';
      } else if (backend === 'cli') {
        payload.cli_path = this.settingsForm?.claude_cli_path || this.runtimeStatus?.cli_binary || '';
        payload.cli_model = this.settingsForm?.claude_cli_model || this.runtimeStatus?.cli_model || '';
      } else if (backend === 'ollama') {
        payload.ollama_model = (typeof this.activeChatModel === 'function'
          ? this.activeChatModel()
          : '') || this.settingsForm?.ollama_model || this.runtimeStatus?.active_model || '';
      }
      return payload;
    },

    async refreshMissionSandbox(t) {
      try {
        const res = await this.api('GET', `/api/tasks/${t.id}/sandbox`);
        this.updateTaskSandboxRecord(t.id, res?.sandbox || null);
        if (res?.sandbox && this.taskSandboxReview?.open && Number(this.taskSandboxReview?.task?.id) === Number(t.id)) {
          this.taskSandboxReview = {
            open: true,
            task: { ...t },
            sandbox: res.sandbox,
          };
        }
      } catch (e) {
        this.showToast(e.message || 'Sandbox not ready yet');
      }
    },

    async viewMissionSandboxReport(t) {
      try {
        const res = await this.api('GET', `/api/tasks/${t.id}/sandbox`);
        this.updateTaskSandboxRecord(t.id, res?.sandbox || null);
        this.taskSandboxReview = {
          open: true,
          task: { ...t },
          sandbox: res?.sandbox || null,
        };
      } catch (e) {
        this.showToast(e.message || 'Sandbox report not ready yet');
      }
    },

    async applyMissionSandbox(t) {
      if (!t?.id) return;
      if (!confirm(`Apply sandbox changes for "${t.title}" to the source workspace?`)) return;
      try {
        const res = await this.api('POST', `/api/tasks/${t.id}/sandbox/apply`);
        this.updateTaskSandboxRecord(t.id, res?.sandbox || null);
        if (this.taskSandboxReview?.open && Number(this.taskSandboxReview?.task?.id) === Number(t.id)) {
          this.taskSandboxReview = {
            open: true,
            task: { ...t },
            sandbox: res?.sandbox || null,
          };
        }
        this.showToast(res?.summary || 'Sandbox changes applied');
      } catch (e) {
        this.showToast(e.message || 'Failed to apply sandbox changes');
      }
    },

    async discardMissionSandbox(t) {
      if (!t?.id) return;
      if (!confirm(`Discard the sandbox for "${t.title}"? This removes the isolated worktree.`)) return;
      try {
        await this.api('DELETE', `/api/tasks/${t.id}/sandbox`);
        this.updateTaskSandboxRecord(t.id, null);
        if (this.taskSandboxReview?.open && Number(this.taskSandboxReview?.task?.id) === Number(t.id)) {
          this.closeMissionSandboxReport();
        }
        this.showToast('Sandbox discarded');
      } catch (e) {
        this.showToast(e.message || 'Failed to discard sandbox');
      }
    },

    closeMissionSandboxReport() {
      this.taskSandboxReview = { open: false, task: null, sandbox: null };
    },

    taskSandboxStatusLabel(status) {
      const key = String(status || 'not_started');
      const map = {
        not_started: 'Not started',
        ready: 'Ready',
        running: 'Running',
        completed: 'Completed',
        review_ready: 'Review ready',
        applied: 'Applied',
        approval_required: 'Awaiting approval',
        error: 'Needs attention',
        missing: 'Missing',
      };
      return map[key] || 'Sandbox';
    },

    taskSandboxStatusClass(status) {
      const key = String(status || 'not_started');
      if (key === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-200';
      if (key === 'review_ready' || key === 'completed') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200';
      if (key === 'applied') return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200';
      if (key === 'approval_required') return 'border-amber-500/30 bg-amber-500/10 text-amber-200';
      if (key === 'error' || key === 'missing') return 'border-rose-500/30 bg-rose-500/10 text-rose-200';
      return 'border-slate-700 bg-slate-900/70 text-slate-300';
    },

    taskSandboxSummary(t) {
      const sandbox = t?.sandbox;
      if (!sandbox) return 'No isolated sandbox created yet.';
      const parts = [
        sandbox.project_name || t.project_name || 'Workspace mission',
        sandbox.branch_name ? `branch ${sandbox.branch_name}` : '',
        sandbox.status === 'applied' ? 'applied to source' : '',
        sandbox.changed_files_count ? `${sandbox.changed_files_count} changed file${sandbox.changed_files_count === 1 ? '' : 's'}` : '',
        sandbox.last_error ? 'needs review' : '',
      ].filter(Boolean);
      return parts.join(' · ') || 'Sandbox ready';
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
