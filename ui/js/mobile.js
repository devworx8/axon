/* ══════════════════════════════════════════════════════════════
   Axon — Mobile / Analysis / SMART Tasks / GitHub / Integrations Module
   ══════════════════════════════════════════════════════════════ */

function axonMobileMixin() {
  return {

    // ── Mobile ─────────────────────────────────────────────────────
    async loadMobileInfo() {
      try {
        const info = await this.api('GET', '/api/mobile/info');
        this.mobileInfo = {
          ...this.mobileInfo,
          ...info,
          _tunnelStarting: false,
          _tunnelStopping: false,
        };
      } catch(e) {
        this.showToast(`Mobile info unavailable: ${e.message || e}`);
      }
    },
    async startTunnel() {
      if (this.mobileInfo._tunnelStarting) return;
      this.mobileInfo = { ...this.mobileInfo, _tunnelStarting: true, _tunnelStopping: false };
      try {
        const r = await this.api('POST', '/api/tunnel/start');
        this.mobileInfo = {
          ...this.mobileInfo,
          tunnel_running: !!r.running,
          cloudflared_url: r.url || this.mobileInfo.cloudflared_url,
          stable_domain_url: r.url || this.mobileInfo.stable_domain_url,
          stable_domain_status: r.mode === 'named' && r.running ? 'configured' : this.mobileInfo.stable_domain_status,
        };
        await this.loadMobileInfo();
        if (r.url) this.showToast(r.mode === 'named' ? '🌐 Named tunnel ready. Use your stable domain.' : '🔒 HTTPS tunnel ready! Scan the QR code.');
        else this.showToast('Tunnel starting — reload in a moment');
      } catch(e) { this.showToast(e.message || 'Failed to start tunnel'); }
      this.mobileInfo = { ...this.mobileInfo, _tunnelStarting: false };
    },
    async stopTunnel() {
      if (this.mobileInfo._tunnelStopping) return;
      this.mobileInfo = { ...this.mobileInfo, _tunnelStopping: true, _tunnelStarting: false };
      try {
        await this.api('POST', '/api/tunnel/stop');
        this.mobileInfo = {
          ...this.mobileInfo,
          tunnel_running: false,
          cloudflared_url: '',
        };
        await this.loadMobileInfo();
        this.showToast('Tunnel stopped');
      } catch(e) {
        this.showToast(`Failed to stop tunnel: ${e.message || e}`);
      } finally {
        this.mobileInfo = { ...this.mobileInfo, _tunnelStopping: false };
      }
    },

    // ── Analysis extras ────────────────────────────────────────────
    async analyseProject(p) {
      this.analysisProject = p;
      this.analysisPanel = true;
      this.analysisLoading = true;
      this.analysisText = '';
      this.analysisChat = [];
      this.analysisFollowup = '';
      this.githubData = null;
      try {
        const res = await this.api('POST', `/api/projects/${p.id}/analyse`);
        this.analysisText = res.analysis;
      } catch(e) { this.analysisText = `⚠️ Error: ${e.message}`; }
      this.loadExpoProjectSummary?.(p, true);
      this.loadExpoProjectBuilds?.(p, true);
      this.analysisLoading = false;
    },

    async sendAnalysisFollowup() {
      const q = this.analysisFollowup.trim();
      if (!q || this.analysisFollowupLoading) return;
      this.analysisChat.push({ role: 'user', content: q });
      this.analysisFollowup = '';
      this.analysisFollowupLoading = true;
      try {
        // Add analysis context to the question
        const contextualQ = `Regarding project "${this.analysisProject?.name}" — previous analysis:\n\n${this.analysisText}\n\nFollow-up: ${q}`;
        const res = await this.api('POST', '/api/chat', {
          message: contextualQ,
          project_id: this.analysisProject?.id || null,
        });
        this.analysisChat.push({ role: 'assistant', content: res.response });
      } catch(e) {
        this.analysisChat.push({ role: 'assistant', content: `⚠️ ${e.message}` });
      }
      this.analysisFollowupLoading = false;
    },

    async loadProjectGithub(p, force = false) {
      if (!p || !this.showGithubStatus) return;
      const cached = this.projectGithubSummaries[p.id];
      if (!force && cached?.raw) {
        this.githubData = cached.raw;
        return;
      }
      try {
        this.githubData = await this.api('GET', `/api/projects/${p.id}/github`);
        this.setProjectGithubSummary(p.id, this.summarizeGithubData(this.githubData));
      } catch(e) { this.showToast('GitHub data unavailable: ' + e.message); }
    },

    // ── SMART Tasks ────────────────────────────────────────────────
    async loadSmartTasks(p) {
      if (!p || this.smartTasksLoading) return;
      this.smartTasksLoading = true;
      this.smartTasks = [];
      try {
        const res = await this.api('POST', `/api/projects/${p.id}/suggest-tasks`);
        this.smartTasks = res.suggestions || [];
        if (this.smartTasks.length === 0) this.showToast('No new missions suggested — workspace looks healthy.');
      } catch(e) {
        this.showToast('Smart tasks failed: ' + e.message);
      }
      this.smartTasksLoading = false;
    },

    async approveSmartTask(task, idx) {
      try {
        await this.api('POST', '/api/tasks', {
          title: task.title,
          detail: task.detail || task.rationale || '',
          priority: task.priority || 'medium',
          project_id: this.analysisProject?.id || null,
        });
        this.smartTasks.splice(idx, 1);
        this.showToast('✓ Mission created');
        // Refresh task count badge
        await this.loadTasks();
      } catch(e) { this.showToast('Failed to add task: ' + e.message); }
    },

    dismissSmartTask(idx) {
      this.smartTasks.splice(idx, 1);
    },

    // ── GitHub ─────────────────────────────────────────────────────
    async checkGithub() {
      try {
        const r = await this.api('GET', '/api/github/status');
        this.githubAvailable = r.available;
      } catch(e) {}
    },

    // ── Integrations ───────────────────────────────────────────────
    async testSlack() {
      try {
        await this.api('POST', '/api/slack/test', { webhook_url: this.settingsForm.slack_webhook_url });
        this.showToast('✅ Slack message sent!');
      } catch(e) { this.showToast('Slack failed: ' + e.message); }
    },

    async testWebhook() {
      const first = this.settingsForm.webhook_urls.split(',')[0].trim();
      if (!first) return;
      try {
        await this.api('POST', '/api/webhooks/test', {
          url: first,
          secret: this.settingsForm.webhook_secret || '',
        });
        this.showToast('✅ Webhook test sent!');
      } catch(e) { this.showToast('Webhook failed: ' + e.message); }
    },

  };
}

window.axonMobileMixin = axonMobileMixin;
