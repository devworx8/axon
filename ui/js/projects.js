/* ══════════════════════════════════════════════════════════════
   Axon — Projects Module
   ══════════════════════════════════════════════════════════════ */

function axonProjectsMixin() {
  return {

    async loadProjects() {
      this.projectsLoading = true;
      try {
        const qs = this.projectStatusFilter ? `?status=${this.projectStatusFilter}` : '';
        this.projects = await this.api('GET', '/api/projects' + qs);
        if (this.showGithubStatus) this.loadProjectGithubSummaries(this.projects);
        else this.projectGithubSummaries = {};
      } catch(e) { this.showToast('Failed to load workspaces'); }
      this.projectsLoading = false;
    },

    setProjectGithubSummary(projectId, summary) {
      this.projectGithubSummaries = { ...this.projectGithubSummaries, [projectId]: summary };
    },

    summarizeGithubData(data) {
      const latest = data?.ci?.latest || {};
      return {
        loading: false,
        error: false,
        open_pr_count: Number(data?.open_pr_count || 0),
        issue_count: Number(data?.issues?.count || 0),
        ci_conclusion: latest?.conclusion || '',
        ci_status: latest?.status || '',
        raw: data,
      };
    },

    projectGithubCiLabel(summary) {
      if (!summary) return 'CI';
      if (summary.loading) return 'CI...';
      if (summary.error) return 'CI ?';
      const state = summary.ci_conclusion || summary.ci_status || '';
      if (!state) return 'CI -';
      if (state === 'success') return 'CI ok';
      if (state === 'failure') return 'CI fail';
      if (state === 'cancelled') return 'CI cancelled';
      if (state === 'in_progress') return 'CI running';
      if (state === 'queued' || state === 'pending' || state === 'requested' || state === 'waiting') return 'CI queued';
      return `CI ${state}`;
    },

    projectGithubCiClass(summary) {
      if (!summary || summary.loading) return 'bg-slate-800/70 text-slate-500 border-slate-700/80';
      if (summary.error) return 'bg-amber-500/10 text-amber-300 border-amber-500/20';
      if (summary.ci_conclusion === 'success') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20';
      if (summary.ci_conclusion === 'failure') return 'bg-rose-500/10 text-rose-300 border-rose-500/20';
      if (summary.ci_status === 'in_progress' || summary.ci_status === 'queued' || summary.ci_status === 'pending') {
        return 'bg-amber-500/10 text-amber-300 border-amber-500/20';
      }
      return 'bg-slate-800/70 text-slate-400 border-slate-700/80';
    },

    async loadProjectGithubSummaries(projects = this.projects) {
      if (!this.showGithubStatus) return;
      const items = Array.isArray(projects) ? projects : [];
      const requestId = Date.now();
      this.projectGithubRequestId = requestId;

      if (!items.length) {
        this.projectGithubSummaries = {};
        return;
      }

      this.projectGithubSummaries = Object.fromEntries(items.map(p => [p.id, { loading: true }]));

      for (const p of items) {
        try {
          const data = await this.api('GET', `/api/projects/${p.id}/github`);
          if (this.projectGithubRequestId !== requestId) return;
          this.setProjectGithubSummary(p.id, this.summarizeGithubData(data));
        } catch(e) {
          if (this.projectGithubRequestId !== requestId) return;
          this.setProjectGithubSummary(p.id, { loading: false, error: true });
        }
      }
    },

    async runScan() {
      this.scanning = true;
      try {
        await this.api('POST', '/api/scan');
        await new Promise(r => setTimeout(r, 4000)); // wait for scan
        await this.loadProjects();
        this.showToast('Axon Scan complete');
      } catch(e) { this.showToast('Axon Scan failed'); }
      this.scanning = false;
    },

    openProjectChat(p) {
      this.chatProjectId = String(p.id);
      this.chatProject = p;
      this.activeTab = 'chat';
    },

    editProjectNote(p) {
      this.noteModal = { open: true, project: p, value: p.note || '' };
    },

    async saveNote() {
      try {
        await this.api('PATCH', `/api/projects/${this.noteModal.project.id}`, { note: this.noteModal.value });
        const idx = this.projects.findIndex(p => p.id === this.noteModal.project.id);
        if (idx >= 0) this.projects[idx].note = this.noteModal.value;
        this.noteModal.open = false;
        this.showToast('Note saved');
      } catch(e) { this.showToast('Save failed'); }
    },

  };
}

window.axonProjectsMixin = axonProjectsMixin;
