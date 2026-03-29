/* ══════════════════════════════════════════════════════════════
   Axon — Dashboard Module
   ══════════════════════════════════════════════════════════════ */

function axonDashboardMixin() {
  return {

    async loadCurrentUser() {
      try {
        const user = await this.api('GET', '/api/users/me');
        if (user && user.id) {
          this.currentUser = user;
        }
      } catch (e) {
        // non-critical — default user state is fine
      }
    },

    toggleLocalToolsPanel() {
      this.composerOptions.terminal_mode = !this.composerOptions.terminal_mode;
      if (this.composerOptions.terminal_mode && !this.terminal.sessions.length) {
        this.createTerminalSession();
      }
    },

    async loadLatestDigest() {
      try {
        const res = await this.api('GET', '/api/digest/latest');
        this.latestDigest = res.digest || null;
      } catch (e) {
        // non-critical
      }
    },

    async loadActivity() {
      try {
        const data = await this.api('GET', '/api/activity?limit=50');
        this.activity = data || [];
      } catch (e) {
        console.error('Failed to load activity', e);
      }
    },

    async loadDashboard() {
      if (this.dashLoading) return;
      this.dashLoading = true;
      try {
        this.loadRuntimeStatus();
        // Load projects, tasks, and activity in parallel
        const [projects, tasks, activity] = await Promise.all([
          this.api('GET', '/api/projects?status=active').catch(() => []),
          this.api('GET', '/api/tasks').catch(() => []),
          this.api('GET', '/api/activity?limit=8').catch(() => []),
        ]);

        // Compute stats
        const allProjects = projects || [];
        const allTasks = tasks || [];
        const active = allProjects.filter(p => p.status === 'active');
        const urgent = allTasks.filter(t => t.priority === 'urgent' && t.status !== 'done');
        const done = allTasks.filter(t => t.status === 'done');
        const healths = active.map(p => p.health || 0).filter(h => h > 0);

        this.dashStats = {
          projects: allProjects.length,
          active: active.length,
          tasks: allTasks.filter(t => t.status !== 'done' && t.status !== 'cancelled').length,
          urgent: urgent.length,
          done: done.length,
          health_avg: healths.length ? Math.round(healths.reduce((a,b) => a+b, 0) / healths.length) : 0,
        };

        // Top projects sorted by health (lowest first — these need attention)
        this.dashTopProjects = active
          .sort((a, b) => (a.health || 0) - (b.health || 0))
          .slice(0, 5);

        this.dashRecentActivity = activity || [];

        // Also update tasks for urgent display
        this.tasks = allTasks;
        this.urgentCount = urgent.length;
      } catch(e) {
        console.error('Dashboard load error:', e);
      } finally {
        this.dashLoading = false;
      }
    },

    async loadRuntimeStatus() {
      try {
        const status = await this.api('GET', '/api/runtime/status');
        this.runtimeStatus = {
          ...this.runtimeStatus,
          ...status,
          local_models: status.local_models || [],
          cloud_agents: status.cloud_agents || [],
          api_providers: status.api_providers || [],
          selected_api_provider: status.selected_api_provider || {},
          phases: status.phases || this.agentLifecycle,
          agents: status.agents || [],
        };
        if (status.browser_actions) {
          this.browserActions = {
            ...this.browserActions,
            ...status.browser_actions,
          };
        }
        if (status.connection) {
          this.connectionState = status.connection;
          this.connectionState.domain_checked_at = new Date().toISOString();
        }
      } catch (e) {
        this.runtimeStatus = {
          ...this.runtimeStatus,
          runtime_state: 'degraded',
          runtime_label: 'Unavailable',
        };
      }
    },

    runtimeStatusCards() {
      return [
        {
          label: 'Runtime',
          value: this.runtimeStatus.runtime_label || 'Standby',
          tone: this.runtimeStatus.runtime_state === 'active' ? 'ok' : 'warn',
        },
        {
          label: 'Active Model',
          value: this.runtimeStatus.active_model || this.activeChatModel() || 'Waiting',
          tone: this.runtimeStatus.active_model ? 'ok' : 'neutral',
        },
        {
          label: 'Secure Vault',
          value: this.runtimeStatus.vault_state || 'Locked',
          tone: (this.runtimeStatus.vault_state || '').toLowerCase().includes('ready') || (this.runtimeStatus.vault_state || '').toLowerCase().includes('unlocked') ? 'ok' : 'warn',
        },
        {
          label: 'Memory',
          value: this.runtimeStatus.memory_overview?.total
            ? `${this.runtimeStatus.memory_state || 'Ready'} · ${this.runtimeStatus.memory_overview.total}`
            : (this.runtimeStatus.memory_state || 'Ready'),
          tone: (this.runtimeStatus.memory_state || '').toLowerCase().includes('ready') ? 'ok' : 'warn',
        },
        {
          label: 'Agents',
          value: `${this.runtimeStatus.active_agents_count ?? 0} online`,
          tone: (this.runtimeStatus.active_agents_count || 0) > 0 ? 'ok' : 'warn',
        },
      ];
    },

    dashboardWeakestWorkspace() {
      return (this.dashTopProjects || [])[0] || null;
    },

    dashboardPriorityMissions() {
      const rank = { urgent: 0, high: 1, medium: 2, low: 3 };
      return (this.tasks || [])
        .filter(task => !['done', 'cancelled'].includes(String(task.status || '').toLowerCase()))
        .sort((a, b) => {
          const priorityDelta = (rank[a.priority] ?? 4) - (rank[b.priority] ?? 4);
          if (priorityDelta !== 0) return priorityDelta;
          return new Date(b.created_at || 0) - new Date(a.created_at || 0);
        })
        .slice(0, 4);
    },

    dashboardLiveEntries() {
      if ((this.liveOperatorFeed || []).length) {
        return [...this.liveOperatorFeed].slice(-6).reverse();
      }
      return (this.dashRecentActivity || []).slice(0, 6).map(item => ({
        id: `activity-${item.id}`,
        phase: item.event_type === 'alert' ? 'recover' : 'observe',
        title: item.summary || this.prettyToolName(item.event_type || 'activity'),
        detail: item.project_name ? `Workspace · ${item.project_name}` : (item.event_type || 'Timeline update'),
        at: item.created_at,
      }));
    },

    tabLabelFor(id) {
      const item = [...this.navItems, ...this.mobileNavItems].find(tab => tab.id === id);
      if (item?.label) return item.label;
      if (id === 'dashboard') return 'Dashboard';
      return (id || '').replace(/[-_]/g, ' ');
    },

    timeAgo(dateStr) {
      if (!dateStr) return '';
      const d = new Date(dateStr + (dateStr.includes('Z') ? '' : 'Z'));
      const now = new Date();
      const diff = Math.floor((now - d) / 1000);
      if (diff < 60) return 'just now';
      if (diff < 3600) return Math.floor(diff/60) + 'm ago';
      if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
      if (diff < 604800) return Math.floor(diff/86400) + 'd ago';
      return d.toLocaleDateString();
    },

    usesOllamaBackend() {
      return (this.settingsForm?.ai_backend || '').toLowerCase() === 'ollama';
    },

    activeChatModel() {
      return this.selectedChatModel || this.settingsForm?.code_model || this.settingsForm?.ollama_model || '';
    },

    providerIdentityIcon(providerId = '') {
      const icons = {
        ollama: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M7 15c0-3.314 2.239-6 5-6s5 2.686 5 6-2.239 4-5 4-5-.686-5-4z"/><path stroke-linecap="round" stroke-linejoin="round" d="M9 10c-.333-2 1-5 3-5 1.48 0 2.44 1.12 3 2.5M10 14h.01M14 14h.01"/></svg>`,
        cli: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6.75h16v10.5H4z"/><path stroke-linecap="round" stroke-linejoin="round" d="m8 10 2 2-2 2m5 0h3"/></svg>`,
        anthropic: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="m6 18 6-12 6 12"/><path stroke-linecap="round" stroke-linejoin="round" d="M8.5 13h7"/></svg>`,
        openai_gpts: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3.5 17.5 6v6L12 15.5 6.5 12V6L12 3.5z"/><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v8M8.5 10 15.5 14M15.5 10 8.5 14"/></svg>`,
        gemini_gems: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="m12 2 2.2 5.8L20 10l-5.8 2.2L12 18l-2.2-5.8L4 10l5.8-2.2L12 2Z"/></svg>`,
        generic_api: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M4 12h16M12 4a9 9 0 0 1 0 16M12 4a9 9 0 0 0 0 16"/></svg>`,
      };
      return icons[providerId] || icons.generic_api;
    },

    providerIdentityTone(providerId = '') {
      if (providerId === 'ollama') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (providerId === 'cli') return 'border-green-500/20 bg-green-500/10 text-green-200';
      if (providerId === 'anthropic') return 'border-orange-500/20 bg-orange-500/10 text-orange-200';
      if (providerId === 'openai_gpts') return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200';
      if (providerId === 'gemini_gems') return 'border-indigo-500/20 bg-indigo-500/10 text-indigo-200';
      return 'border-blue-500/20 bg-blue-500/10 text-blue-200';
    },

    consoleProviderIdentity() {
      const backend = (this.settingsForm?.ai_backend || 'ollama').toLowerCase();
      if (backend === 'ollama') {
        return {
          providerId: 'ollama',
          providerLabel: 'Ollama',
          modelLabel: this.activeChatModel() || this.settingsForm?.code_model || this.settingsForm?.ollama_model || this.runtimeStatus?.active_model || 'Saved default',
          transportLabel: 'Local runtime',
        };
      }
      if (backend === 'api') {
        return {
          providerId: this.runtimeStatus?.selected_api_provider?.provider_id || this.settingsForm?.api_provider || 'generic_api',
          providerLabel: this.selectedApiProviderLabel(),
          modelLabel: this.selectedApiProviderModel() || this.runtimeStatus?.active_model || 'Model pending',
          transportLabel: this.selectedApiProviderTransportLabel(),
        };
      }
      return {
        providerId: 'cli',
        providerLabel: 'CLI Agent',
        modelLabel: this.runtimeStatus?.active_model || this.settingsForm?.code_model || this.settingsForm?.ollama_model || 'Saved default',
        transportLabel: 'Local bridge',
      };
    },

    assistantProviderIdentity() {
      const identity = this.consoleProviderIdentity();
      return {
        providerId: identity.providerId,
        providerLabel: identity.providerLabel,
        modelLabel: identity.modelLabel,
        transportLabel: identity.transportLabel,
      };
    },

    messageProviderIdentity(message) {
      const identity = message?.providerIdentity || {};
      if (identity.providerId || identity.providerLabel || identity.modelLabel) {
        return identity;
      }
      return this.consoleProviderIdentity();
    },

    syncChatModel(preferred = '') {
      const installed = (this.ollamaModels || []).map(m => m.name);
      const candidates = [
        preferred,
        this.selectedChatModel,
        this.settingsForm?.code_model || '',
        this.settingsForm?.ollama_model || '',
      ].filter(Boolean);
      const installedMatch = candidates.find(name => installed.includes(name));
      if (installedMatch) {
        this.selectedChatModel = installedMatch;
        return;
      }
      if (!candidates.length && installed.length) {
        this.selectedChatModel = installed[0];
        return;
      }
      if (candidates.length) {
        this.selectedChatModel = candidates[0];
      } else if (!this.selectedChatModel) {
        this.selectedChatModel = '';
      }
    },

    composerModelMeta() {
      return (this.ollamaModels || []).find(m => m.name === this.activeChatModel()) || null;
    },

    composerModelSummary() {
      const meta = this.composerModelMeta();
      if (!meta) return this.activeChatModel() || 'Model follows your saved default';
      const parts = [];
      if (meta.parameter_size) parts.push(meta.parameter_size);
      if (meta.size_gb) parts.push(`${meta.size_gb} GB`);
      if (meta.family) parts.push(meta.family);
      return parts.join(' · ') || meta.name;
    },

    backendBadge() {
      const backend = (this.settingsForm?.ai_backend || 'ollama').toLowerCase();
      if (backend === 'ollama') return 'Local Ollama';
      if (backend === 'cli') return 'CLI Agent';
      return this.selectedApiProviderLabel();
    },

    ollamaRuntimeModeLabel(mode = '') {
      const resolved = String(
        mode
        || this.ollamaStatus?.runtime_mode
        || this.runtimeStatus?.ollama_runtime_mode
        || this.settingsForm?.ollama_runtime_mode
        || 'gpu_default'
      ).toLowerCase();
      return resolved === 'cpu_safe' ? 'CPU Safe' : 'GPU Default';
    },

    ollamaStatusLabel() {
      if (!this.ollamaStatus?.running) return 'Ollama not detected';
      return `Ollama running (${this.ollamaRuntimeModeLabel()})`;
    },

    selectedApiProviderLabel() {
      return this.runtimeStatus?.selected_api_provider?.provider_label
        || this.activeApiProviderCard()?.label
        || 'External API';
    },

    selectedApiProviderModel() {
      return this.runtimeStatus?.selected_api_provider?.api_model
        || this.providerValue(this.settingsForm?.api_provider || 'anthropic', 'model')
        || '';
    },

    selectedApiProviderTransportLabel() {
      const transport = this.runtimeStatus?.selected_api_provider?.transport || this.activeApiProviderCard()?.transport || 'api';
      if (transport === 'openai_compatible') return 'OpenAI-compatible';
      if (transport === 'gemini') return 'Gemini';
      if (transport === 'anthropic') return 'Anthropic Messages';
      return transport;
    },

    consoleRuntimeLabel() {
      const backend = (this.settingsForm?.ai_backend || 'ollama').toLowerCase();
      if (backend === 'ollama') {
        return this.activeChatModel() || this.settingsForm.code_model || this.settingsForm.ollama_model || 'pick a model';
      }
      if (backend === 'api') {
        const provider = this.selectedApiProviderLabel();
        const model = this.selectedApiProviderModel();
        return model ? `${provider} · ${model}` : provider;
      }
      return 'CLI agent';
    },

    assistantRuntimeLabel() {
      if (this.usesOllamaBackend()) return this.activeChatModel();
      const backend = (this.settingsForm?.ai_backend || '').toLowerCase();
      if (backend === 'api') {
        const provider = this.selectedApiProviderLabel();
        const model = this.selectedApiProviderModel();
        return model ? `${provider} · ${model}` : provider;
      }
      return 'CLI Agent';
    },

    browserActionRiskClass(risk) {
      const value = String(risk || 'medium').toLowerCase();
      if (value === 'high') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      if (value === 'low') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
    },

    browserActionScopeLabel(scope) {
      const value = String(scope || 'browser_act').toLowerCase();
      if (value === 'browser_inspect') return 'Inspect';
      if (value === 'browser_act') return 'Act';
      return value.replace(/_/g, ' ');
    },

    browserActionIcon(actionType) {
      const value = String(actionType || '').toLowerCase();
      if (value.includes('navigate') || value.includes('open')) return '↗';
      if (value.includes('click') || value.includes('press')) return '⌖';
      if (value.includes('type') || value.includes('fill')) return '⌨';
      if (value.includes('inspect') || value.includes('snapshot')) return '◫';
      if (value.includes('submit')) return '⤴';
      return '◦';
    },

    async loadBrowserActions() {
      this.browserActions.loading = true;
      try {
        const state = await this.api('GET', '/api/browser/actions');
        this.browserActions = {
          ...this.browserActions,
          ...state,
          loading: false,
        };
      } catch (e) {
        this.browserActions.loading = false;
        this.showToast(`Browser actions unavailable: ${e.message || e}`);
      }
    },

    async approveBrowserAction(id) {
      if (!id) return;
      this.browserActions.loading = true;
      try {
        const state = await this.api('POST', `/api/browser/actions/${id}/approve`);
        this.browserActions = {
          ...this.browserActions,
          ...state,
          loading: false,
        };
        this.showToast('Browser action approved');
      } catch (e) {
        this.browserActions.loading = false;
        this.showToast(`Approval failed: ${e.message || e}`);
      }
    },

    async rejectBrowserAction(id) {
      if (!id) return;
      this.browserActions.loading = true;
      try {
        const state = await this.api('POST', `/api/browser/actions/${id}/reject`);
        this.browserActions = {
          ...this.browserActions,
          ...state,
          loading: false,
        };
        this.showToast('Browser action rejected');
      } catch (e) {
        this.browserActions.loading = false;
        this.showToast(`Reject failed: ${e.message || e}`);
      }
    },

    runtimeProviderBadges() {
      const badges = [
        {
          label: `Runtime · ${this.backendBadge()}`,
          tone: this.usesOllamaBackend() ? 'ok' : 'info',
        },
      ];
      if (!this.usesOllamaBackend()) {
        badges.push({
          label: `Model · ${this.selectedApiProviderModel() || 'pending'}`,
          tone: this.selectedApiProviderModel() ? 'neutral' : 'warn',
        });
      }
      const enabledAdapters = (this.runtimeStatus.cloud_agents || []).filter(item => item.enabled);
      badges.push({
        label: enabledAdapters.length
          ? `Adapters · ${enabledAdapters.map(item => item.label).join(', ')}`
          : 'Adapters · local-only',
        tone: enabledAdapters.length ? 'info' : 'neutral',
      });
      if (this.usage.ollama_calls > 0) {
        badges.push({ label: `Local calls · ${this.usage.ollama_calls}`, tone: 'ok' });
      }
      if (this.usage.api_calls > 0) {
        badges.push({ label: `Cloud calls · ${this.usage.api_calls}`, tone: 'info' });
      }
      if (this.usage.cli_calls > 0) {
        badges.push({ label: `CLI calls · ${this.usage.cli_calls}`, tone: 'neutral' });
      }
      return badges;
    },

    timelineRuntimeBadges() {
      const badges = [
        {
          label: `Runtime ${this.runtimeStatus.runtime_label || this.backendBadge()}`,
          tone: this.runtimeStatus.runtime_state === 'active' ? 'ok' : 'warn',
        },
        {
          label: `Model ${this.runtimeStatus.active_model || this.selectedApiProviderModel() || 'pending'}`,
          tone: (this.runtimeStatus.active_model || this.selectedApiProviderModel()) ? 'neutral' : 'warn',
        },
      ];
      if (!this.usesOllamaBackend()) {
        badges.push({
          label: `Provider ${this.selectedApiProviderLabel()}`,
          tone: 'info',
        });
      }
      const enabledAdapters = (this.runtimeStatus.cloud_agents || []).filter(item => item.enabled);
      badges.push({
        label: enabledAdapters.length ? `Cloud adapters ${enabledAdapters.length}` : 'Cloud adapters off',
        tone: enabledAdapters.length ? 'info' : 'neutral',
      });
      if (this.runtimeStatus.gpu_guard?.warning) {
        badges.push({ label: 'GPU guard active', tone: 'warn' });
      }
      return badges;
    },

    runtimeProviderBadgeClass(tone) {
      return {
        ok: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
        warn: 'border-amber-500/20 bg-amber-500/10 text-amber-200',
        info: 'border-blue-500/20 bg-blue-500/10 text-blue-200',
        neutral: 'border-slate-700 bg-slate-950/60 text-slate-400',
      }[tone || 'neutral'] || 'border-slate-700 bg-slate-950/60 text-slate-400';
    },

    settingEnabled(value) {
      if (typeof value === 'boolean') return value;
      return ['1', 'true', 'yes', 'on'].includes(String(value || '').toLowerCase());
    },

    roleSettingKey(role) {
      return `${role}_model`;
    },

    cloudAdapterKey(adapterId) {
      return `${adapterId}_enabled`;
    },

    providerKeyField(providerId) {
      const map = {
        anthropic: 'anthropic_api_key',
        openai_gpts: 'openai_api_key',
        gemini_gems: 'gemini_api_key',
        deepseek: 'deepseek_api_key',
        generic_api: 'generic_api_key',
      };
      return map[providerId] || '';
    },

    providerBaseField(providerId) {
      const map = {
        anthropic: 'anthropic_base_url',
        openai_gpts: 'openai_base_url',
        gemini_gems: 'gemini_base_url',
        deepseek: 'deepseek_base_url',
        generic_api: 'generic_api_url',
      };
      return map[providerId] || '';
    },

    providerModelField(providerId) {
      const map = {
        anthropic: 'anthropic_api_model',
        openai_gpts: 'openai_api_model',
        gemini_gems: 'gemini_api_model',
        deepseek: 'deepseek_api_model',
        generic_api: 'generic_api_model',
      };
      return map[providerId] || '';
    },

    providerHintField(providerId) {
      const map = {
        anthropic: '_anthropicKeyHint',
        openai_gpts: '_openaiKeyHint',
        gemini_gems: '_geminiKeyHint',
        deepseek: '_deepseekKeyHint',
        generic_api: '_genericKeyHint',
      };
      return map[providerId] || '';
    },

    activeApiProviderCard() {
      const id = this.settingsForm?.api_provider || 'anthropic';
      return (this.runtimeStatus.api_providers || []).find(provider => provider.id === id) || null;
    },

    providerValue(providerId, kind) {
      const field = kind === 'api_key'
        ? this.providerKeyField(providerId)
        : kind === 'base_url'
          ? this.providerBaseField(providerId)
          : this.providerModelField(providerId);
      return field ? (this.settingsForm?.[field] || '') : '';
    },

    setProviderValue(providerId, kind, value) {
      const field = kind === 'api_key'
        ? this.providerKeyField(providerId)
        : kind === 'base_url'
          ? this.providerBaseField(providerId)
          : this.providerModelField(providerId);
      if (field) this.settingsForm[field] = value;
    },

    providerSavedHint(providerId) {
      const field = this.providerHintField(providerId);
      return field ? (this.settingsForm?.[field] || '') : '';
    },

    providerKeyPlaceholder(providerId) {
      if (providerId === 'anthropic') return 'sk-ant-...';
      if (providerId === 'gemini_gems') return 'AIza...';
      if (providerId === 'deepseek') return 'sk-...';
      return 'Paste provider key';
    },

    providerRuntimeHint(providerId) {
      const card = (this.runtimeStatus.api_providers || []).find(provider => provider.id === providerId)
        || (this.runtimeStatus.cloud_agents || []).find(provider => provider.id === providerId);
      if (!card) return 'External adapter configuration stays isolated from local-only workflows.';
      const base = card.base_url || card.default_base_url || 'custom endpoint';
      const model = this.providerValue(providerId, 'model') || card.default_model || 'provider default';
      return `${card.label} will use ${model} via ${base}.`;
    },

    updateProviderKeyHint(providerId) {
      const value = this.providerValue(providerId, 'api_key');
      const hintField = this.providerHintField(providerId);
      const keyField = this.providerKeyField(providerId);
      if (!hintField || !keyField) return;
      if (value) {
        this.settingsForm[hintField] = value.length > 10 ? `${value.slice(0, 4)}...${value.slice(-4)}` : 'set';
        this.settingsForm[keyField] = '';
      }
    },

    async loadTtsVoices(force = false) {
      if (this.ttsVoicesLoading) return;
      if (!force && this.ttsVoices.length) return;
      this.ttsVoicesLoading = true;
      try {
        const data = await this.api('GET', '/api/tts/voices');
        this.ttsVoices = data.voices || [];
        this.ttsVoicesMeta = {
          source: data.source || 'fallback',
          live: !!data.live,
          region: data.region || this.settingsForm.azure_speech_region || 'eastus',
          warning: data.warning || '',
        };
      } catch (e) {
        this.ttsVoicesMeta = {
          source: 'fallback',
          live: false,
          region: this.settingsForm.azure_speech_region || 'eastus',
          warning: e.message || 'Voice catalog unavailable',
        };
      }
      this.ttsVoicesLoading = false;
    },

    filteredTtsVoices() {
      const query = (this.azureVoiceQuery || '').toLowerCase().trim();
      const voices = this.ttsVoices || [];
      if (!query) return voices;
      return voices.filter(voice => [
        voice.id,
        voice.name,
        voice.local_name,
        voice.lang,
        voice.gender,
        voice.multilingual ? 'multilingual' : '',
      ].some(value => String(value || '').toLowerCase().includes(query)));
    },

    voiceOptionLabel(voice) {
      if (!voice) return '';
      const parts = [
        voice.id,
        voice.local_name && voice.local_name !== voice.name ? `${voice.name} / ${voice.local_name}` : voice.name,
        voice.lang,
        voice.gender,
      ].filter(Boolean);
      if (voice.multilingual) parts.push('Multilingual');
      return parts.join(' — ');
    },

    async testCloudProvider(providerId) {
      const card = (this.runtimeStatus.api_providers || []).find(provider => provider.id === providerId)
        || (this.runtimeStatus.cloud_agents || []).find(provider => provider.id === providerId);
      if (!card) return;
      this.cloudProviderTests[providerId] = { ok: false, message: 'Testing…' };
      try {
        const res = await this.api('POST', '/api/cloud/providers/test', {
          provider_id: providerId,
          api_key: this.providerValue(providerId, 'api_key') || undefined,
          base_url: this.providerValue(providerId, 'base_url') || undefined,
          model: this.providerValue(providerId, 'model') || undefined,
        });
        this.cloudProviderTests[providerId] = {
          ok: !!res.ok,
          message: res.message || (res.ok ? `${card.label} ready.` : `${card.label} test failed.`),
        };
        if (res.ok) {
          this.updateProviderKeyHint(providerId);
        }
      } catch (e) {
        this.cloudProviderTests[providerId] = { ok: false, message: e.message || 'Provider test failed.' };
      }
    },

    routeMatchesFamily(name, model) {
      const lower = String(name || '').toLowerCase();
      const families = [model.default_family, ...(model.fallbacks || [])]
        .filter(Boolean)
        .map(item => String(item).toLowerCase());
      return families.some(prefix => lower.startsWith(prefix));
    },

    modelOptionsForRole(model) {
      const key = this.roleSettingKey(model.role);
      const current = this.settingsForm?.[key] || '';
      const installed = (this.ollamaModels || [])
        .filter(item => this.routeMatchesFamily(item.name, model))
        .map(item => ({
          value: item.name,
          label: item.size_gb ? `${item.name} — ${item.size_gb}GB` : item.name,
        }));
      if (current && !installed.some(item => item.value === current)) {
        installed.unshift({ value: current, label: `${current} — saved` });
      }
      return installed;
    },

    routePreviewText(model) {
      const key = this.roleSettingKey(model.role);
      const configured = this.settingsForm?.[key] || '';
      if (configured) {
        return `${model.label} is pinned to ${configured}, with ${model.match_count || 0} matching local install${(model.match_count || 0) === 1 ? '' : 's'} available.`;
      }
      if (model.resolved_model) {
        return `${model.label} is auto-routing to ${model.resolved_model} from the ${model.default_family} family.`;
      }
      return `${model.label} will auto-discover a local match from ${model.default_family}. Install one of the listed family matches to activate it.`;
    },

    intelligenceModes() {
      return [
        { value: 'ask', label: 'Ask' },
        { value: 'deep_research', label: 'Deep Research' },
        { value: 'analyze', label: 'Analyze' },
        { value: 'summarize', label: 'Summarize' },
        { value: 'explain', label: 'Explain' },
        { value: 'compare', label: 'Compare' },
        { value: 'build_brief', label: 'Build Brief' },
      ];
    },

    actionModes() {
      return [
        { value: '', label: 'None' },
        { value: 'execute_task', label: 'Execute Task' },
        { value: 'fix_repair', label: 'Fix / Repair' },
        { value: 'generate', label: 'Generate' },
        { value: 'refactor', label: 'Refactor' },
        { value: 'optimize', label: 'Optimize' },
        { value: 'scan_workspace', label: 'Scan Workspace' },
        { value: 'review_output', label: 'Review Output' },
      ];
    },

    agentModes() {
      return [
        { value: '', label: 'Auto' },
        { value: 'planner', label: 'Planner Mode' },
        { value: 'coder', label: 'Coder Mode' },
        { value: 'scanner', label: 'Scanner Mode' },
        { value: 'reviewer', label: 'Reviewer Mode' },
        { value: 'repair', label: 'Repair Mode' },
        { value: 'multi_agent', label: 'Multi-Agent' },
      ];
    },

    externalModes() {
      return [
        { value: 'local_first', label: 'Local First' },
        { value: 'cloud_assist', label: 'Use Cloud Assist' },
        { value: 'external_agent', label: 'Use External Agent' },
        { value: 'disable_external_calls', label: 'Disable External Calls' },
      ];
    },

    setComposerOption(key, value) {
      if (!this.composerOptions) return;
      this.composerOptions[key] = value;
    },

    toggleComposerFlag(key) {
      if (!this.composerOptions) return;
      this.composerOptions[key] = !this.composerOptions[key];
    },

    openComposerMenu() {
      this.showComposerMenu = !this.showComposerMenu;
      if (this.showComposerMenu) this.showResourcePicker = false;
    },

    normalizedComposerOptions() {
      const raw = this.composerOptions || {};
      const researchPack = this.currentResearchPack();
      const normalized = {
        intelligence_mode: raw.intelligence_mode || 'ask',
        use_workspace_memory: raw.use_workspace_memory !== false,
        safe_mode: raw.safe_mode !== false,
        external_mode: raw.external_mode || 'local_first',
      };
      if (raw.action_mode) normalized.action_mode = raw.action_mode;
      if (raw.pin_context) normalized.pin_context = true;
      if (raw.include_timeline_history) normalized.include_timeline_history = true;
      if (raw.agent_role) normalized.agent_role = raw.agent_role;
      if (raw.require_approval) normalized.require_approval = true;
      if (raw.simulation_mode) normalized.simulation_mode = true;
      if (raw.terminal_mode) normalized.terminal_mode = true;
      if (raw.live_desktop_feed) normalized.live_desktop_feed = true;
      if (raw.external_provider_hint) normalized.external_provider_hint = raw.external_provider_hint;
      if (researchPack) {
        normalized.research_pack_id = Number(researchPack.id);
        normalized.research_pack_title = researchPack.title;
      }
      return normalized;
    },

    composerSummaryChips() {
      const opts = this.normalizedComposerOptions();
      const chips = [];
      if (opts.intelligence_mode && opts.intelligence_mode !== 'ask') {
        chips.push({ key: 'intelligence_mode', label: opts.intelligence_mode.replace(/_/g, ' ') });
      }
      if (opts.action_mode) chips.push({ key: 'action_mode', label: opts.action_mode.replace(/_/g, ' ') });
      if (opts.agent_role) chips.push({ key: 'agent_role', label: `${opts.agent_role} mode` });
      if (opts.include_timeline_history) chips.push({ key: 'include_timeline_history', label: 'timeline history' });
      if (opts.pin_context) chips.push({ key: 'pin_context', label: 'pin context' });
      if (opts.require_approval) chips.push({ key: 'require_approval', label: 'approval' });
      if (opts.simulation_mode) chips.push({ key: 'simulation_mode', label: 'simulation' });
      if (opts.terminal_mode) chips.push({ key: 'terminal_mode', label: 'terminal' });
      if (opts.live_desktop_feed) chips.push({ key: 'live_desktop_feed', label: 'live desktop' });
      if (opts.use_workspace_memory === false) chips.push({ key: 'use_workspace_memory', label: 'workspace memory off' });
      if (opts.safe_mode === false) chips.push({ key: 'safe_mode', label: 'safe mode off' });
      if (opts.external_mode && opts.external_mode !== 'local_first') {
        const labelMap = {
          disable_external_calls: 'local only',
          cloud_assist: opts.external_provider_hint ? opts.external_provider_hint.replace(/_/g, ' ') : 'cloud assist',
          external_agent: 'external agent',
        };
        chips.push({ key: 'external_mode', label: labelMap[opts.external_mode] || opts.external_mode.replace(/_/g, ' ') });
      }
      if (opts.research_pack_title) chips.push({ key: 'research_pack_id', label: `pack: ${opts.research_pack_title}` });
      return chips;
    },

    removeComposerChip(key) {
      if (!this.composerOptions) return;
      if (key === 'intelligence_mode') this.composerOptions.intelligence_mode = 'ask';
      else if (key === 'action_mode') this.composerOptions.action_mode = '';
      else if (key === 'agent_role') this.composerOptions.agent_role = '';
      else if (key === 'external_mode') this.composerOptions.external_mode = 'local_first';
      else if (key === 'research_pack_id') this.selectedResearchPackId = null;
      else if (key === 'terminal_mode') { this.composerOptions.terminal_mode = false; this.terminal.panelOpen = false; }
      else if (key === 'use_workspace_memory' || key === 'safe_mode') this.composerOptions[key] = true;
      else this.composerOptions[key] = false;
    },

    memoryOverviewText() {
      const overview = this.runtimeStatus?.memory_overview || {};
      const total = overview.total || 0;
      if (!total) return 'Memory is ready to learn from workspaces, resources, missions, and preferences.';
      const layers = overview.layers || {};
      return `${total} items · ${layers.workspace || 0} workspace · ${layers.resource || 0} resource · ${layers.mission || 0} mission · ${layers.user || 0} user`;
    },

    composerPreferredMode(msg) {
      const opts = this.normalizedComposerOptions();
      if (opts.action_mode && ['execute_task', 'fix_repair', 'optimize', 'refactor'].includes(opts.action_mode)) {
        return 'agent';
      }
      if (opts.agent_role) return 'agent';
      if (opts.intelligence_mode === 'analyze') {
        return this.shouldAutoUseAgent(msg) ? 'agent' : 'chat';
      }
      if (opts.intelligence_mode === 'deep_research') return 'chat';
      if (opts.intelligence_mode === 'build_brief') return 'chat';
      if (opts.action_mode === 'generate') return 'chat';
      return '';
    },

    chatComposerPlaceholder() {
      if (this.businessMode) {
        if (this.businessView === 'quote') return 'Create a quote for Khanyisa with line items, discount, and total...';
        if (this.businessView === 'client') return 'Draft a client profile, follow-up email, or billing summary...';
        if (this.businessView === 'receipt') return 'Create a receipt with payment confirmation details...';
        return 'Create an invoice with line items, discount, due date, and client details...';
      }
      const agent = this.resolveChatMode(this.chatInput) === 'agent';
      const opts = this.normalizedComposerOptions();
      if (!agent) {
        if (opts.intelligence_mode === 'deep_research') return 'Ask Axon to research, synthesize, and explain...';
        if (opts.action_mode === 'generate') return 'Tell Axon what to create...';
        return 'Give Axon a goal, task, or command...';
      }
      return this.isMobile
        ? 'Give Axon a goal, task, or command...'
        : 'Give Axon a goal, task, or command...';
    },

    toggleBusinessMode(force = null) {
      this.businessMode = typeof force === 'boolean' ? force : !this.businessMode;
      if (this.businessMode) {
        this.agentMode = false;
        this.composerOptions.intelligence_mode = 'build_brief';
        this.composerOptions.action_mode = 'generate';
      }
    },

    setBusinessView(view) {
      this.businessView = view;
      this.businessDraft.docType =
        view === 'quote' ? 'quote'
        : view === 'receipt' ? 'receipt'
        : view === 'client' ? 'client'
        : 'invoice';
    },

    addBusinessItem() {
      this.businessDraft.items.push({
        description: '',
        qty: 1,
        rate: 0,
      });
    },

    removeBusinessItem(index) {
      this.businessDraft.items.splice(index, 1);
    },

    businessSubtotal() {
      return (this.businessDraft.items || []).reduce((sum, item) => {
        const qty = Number(item.qty || 0);
        const rate = Number(item.rate || 0);
        return sum + (qty * rate);
      }, 0);
    },

    businessDiscountAmount() {
      const subtotal = this.businessSubtotal();
      const value = Number(this.businessDraft.discountValue || 0);
      if (this.businessDraft.discountType === 'percent') {
        return subtotal * (value / 100);
      }
      return value;
    },

    businessTotal() {
      return Math.max(0, this.businessSubtotal() - this.businessDiscountAmount());
    },

    formatMoney(amount) {
      const value = Number(amount || 0);
      return new Intl.NumberFormat('en-ZA', {
        style: 'currency',
        currency: this.businessDraft.currency || 'ZAR',
      }).format(value);
    },

    businessComposerPrompt(type = 'invoice') {
      const client = this.businessDraft.client.name || 'the client';
      const subtotal = this.businessSubtotal();
      const discount = this.businessDiscountAmount();
      const total = this.businessTotal();
      const lines = (this.businessDraft.items || [])
        .map(i => `- ${i.description || 'Item'} | qty ${i.qty || 1} | rate ${i.rate || 0}`)
        .join('\n');

      return [
        `Create a professional ${type} for ${client}.`,
        `Currency: ${this.businessDraft.currency}.`,
        `Issue date: ${this.businessDraft.issueDate || 'not set'}.`,
        `Due date: ${this.businessDraft.dueDate || 'not set'}.`,
        `Client email: ${this.businessDraft.client.email || 'not provided'}.`,
        `Line items:`,
        lines || '- No items yet',
        `Subtotal: ${subtotal}`,
        `Discount: ${discount}`,
        `Total: ${total}`,
        `Include a clean client-ready breakdown, summary, and payment wording.`,
      ].join('\n');
    },

    injectBusinessPrompt(type = 'invoice') {
      this.setBusinessView(type);
      this.businessMode = true;
      this.chatInput = this.businessComposerPrompt(type);
      if (typeof this.resetChatComposerHeight === 'function') {
        this.resetChatComposerHeight();
      }
      if (typeof this.showToast === 'function') {
        this.showToast(`${type.charAt(0).toUpperCase() + type.slice(1)} draft loaded into composer`);
      }
    },

    phaseChipClass(phase) {
      const active = phase === this.agentProgressState;
      if (active) {
        return 'border-amber-400/40 bg-amber-500/12 text-amber-200';
      }
      return 'border-slate-800 bg-slate-900/70 text-slate-500';
    },

    phaseLabel(phase) {
      const raw = String(phase || 'observe').trim().toLowerCase();
      return raw ? `${raw.charAt(0).toUpperCase()}${raw.slice(1)}` : 'Observe';
    },

    prettyToolName(name) {
      const raw = String(name || '').trim().replace(/[_-]+/g, ' ');
      return raw ? raw.replace(/\b\w/g, ch => ch.toUpperCase()) : 'tool';
    },

    operatorProgressWidth() {
      const phase = this.liveOperator.phase || this.agentProgressState || 'observe';
      const idx = Math.max(this.agentLifecycle.indexOf(phase), 0);
      return `${Math.max(16, ((idx + 1) / this.agentLifecycle.length) * 100)}%`;
    },

    pushLiveOperatorFeed(phase, title, detail = '') {
      const entry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        phase: phase || 'observe',
        title: title || 'Working',
        detail: detail || '',
        at: new Date().toISOString(),
      };
      const last = this.liveOperatorFeed[this.liveOperatorFeed.length - 1];
      if (last && last.phase === entry.phase && last.title === entry.title && last.detail === entry.detail) return;
      this.liveOperatorFeed = [...this.liveOperatorFeed.slice(-5), entry];
    },

    beginLiveOperator(mode, msg = '') {
      if (this.liveOperatorTimer) clearTimeout(this.liveOperatorTimer);
      this.liveOperator = {
        active: true,
        mode,
        phase: mode === 'agent' ? 'observe' : 'plan',
        title: mode === 'agent' ? 'Observing the task' : 'Opening the reply stream',
        detail: mode === 'agent'
          ? 'Axon is checking your goal and lining up the first safe step.'
          : 'Axon is preparing a response.',
        tool: '',
        startedAt: new Date().toISOString(),
      };
      this.liveOperatorFeed = [];
      this.pushLiveOperatorFeed(
        this.liveOperator.phase,
        this.liveOperator.title,
        msg ? `Goal received: ${msg.slice(0, 120)}` : this.liveOperator.detail,
      );
      if (mode === 'agent') this.setAgentStage('observe');
      if (this.desktopPreview.enabled) {
        this.refreshDesktopPreview(true);
        this.scheduleDesktopPreview();
      }
    },

    updateLiveOperator(mode, event = {}) {
      if (!this.liveOperator.active) this.beginLiveOperator(mode);
      if (mode !== 'agent') {
        if (event.error) {
          this.liveOperator = {
            ...this.liveOperator,
            active: true,
            phase: 'recover',
            title: 'Reply interrupted',
            detail: event.error,
          };
          this.pushLiveOperatorFeed('recover', 'Reply interrupted', event.error);
          return;
        }
        if (event.done) {
          this.liveOperator = {
            ...this.liveOperator,
            active: true,
            phase: 'verify',
            title: 'Reply complete',
            detail: 'Axon finished streaming the answer.',
          };
          this.pushLiveOperatorFeed('verify', 'Reply complete', 'Axon finished streaming the answer.');
          return;
        }
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'execute',
          title: 'Writing the reply',
          detail: 'Live response is flowing into the console now.',
        };
        this.pushLiveOperatorFeed('execute', 'Writing the reply', 'Live response is flowing into the console now.');
        return;
      }

      if (event.type === 'tool_call') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'execute',
          title: `Running ${this.prettyToolName(event.name)}`,
          detail: event.args ? JSON.stringify(event.args).slice(0, 96) : 'Using a local operator tool.',
          tool: event.name || '',
        };
        this.pushLiveOperatorFeed('execute', `Running ${this.prettyToolName(event.name)}`, event.args ? JSON.stringify(event.args).slice(0, 96) : 'Using a local operator tool.');
        return;
      }
      if (event.type === 'tool_result') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'verify',
          title: `Checking ${this.prettyToolName(event.name)}`,
          detail: (event.result || 'Axon is reviewing the tool output.').slice(0, 120),
          tool: event.name || this.liveOperator.tool,
        };
        this.pushLiveOperatorFeed('verify', `Checking ${this.prettyToolName(event.name)}`, (event.result || 'Axon is reviewing the tool output.').slice(0, 120));
        return;
      }
      if (event.type === 'text') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: this.liveOperator.tool ? 'verify' : 'plan',
          title: this.liveOperator.tool ? 'Writing the result' : 'Planning the next step',
          detail: this.liveOperator.tool
            ? 'Axon is turning tool output into a final answer.'
            : 'Axon is reasoning through the task before it acts.',
        };
        this.pushLiveOperatorFeed(
          this.liveOperator.tool ? 'verify' : 'plan',
          this.liveOperator.tool ? 'Writing the result' : 'Planning the next step',
          this.liveOperator.tool
            ? 'Axon is turning tool output into a final answer.'
            : 'Axon is reasoning through the task before it acts.',
        );
        return;
      }
      if (event.type === 'done') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'verify',
          title: 'Task complete',
          detail: 'Axon finished the operator pass.',
        };
        this.pushLiveOperatorFeed('verify', 'Task complete', 'Axon finished the operator pass.');
        return;
      }
      if (event.type === 'error') {
        this.liveOperator = {
          ...this.liveOperator,
          active: true,
          phase: 'recover',
          title: 'Needs attention',
          detail: event.message || 'Axon hit an error and stopped safely.',
        };
        this.pushLiveOperatorFeed('recover', 'Needs attention', event.message || 'Axon hit an error and stopped safely.');
      }
    },

    clearLiveOperator(delay = 0) {
      if (this.liveOperatorTimer) clearTimeout(this.liveOperatorTimer);
      const reset = () => {
        this.liveOperator = {
          active: false,
          mode: 'chat',
          phase: 'observe',
          title: '',
          detail: '',
          tool: '',
          startedAt: '',
        };
        this.stopDesktopPreview();
      };
      if (delay > 0) {
        this.liveOperatorTimer = setTimeout(reset, delay);
      } else {
        reset();
      }
    },

    rememberOperatorOutcome(mode, message) {
      const content = String(message?.content || '').replace(/\s+/g, ' ').trim();
      const latestEvent = [...(message?.agentEvents || [])].reverse()
        .find(ev => ev.type === 'tool_result' || ev.type === 'tool_call');
      this.lastOperatorOutcome = {
        title: mode === 'agent' ? 'Axon finished this task' : 'Axon finished the reply',
        summary: (content || latestEvent?.result || 'Completed.').slice(0, 180),
        tool: latestEvent?.name || '',
        at: new Date().toISOString(),
      };
    },

    async refreshDesktopPreview(force = false) {
      if (!this.desktopPreview.enabled && !force) return;
      this.desktopPreview.loading = true;
      this.desktopPreview.error = '';
      try {
        const resp = await fetch('/api/desktop/preview?w=960&h=540', {
          headers: this.authHeaders(),
          cache: 'no-store',
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          throw new Error('Session expired');
        }
        // Handle structured JSON error responses (no_display / capture_failed)
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
          const body = await resp.json();
          const msg = body.message || body.detail || 'Desktop preview unavailable';
          throw new Error(body.status === 'no_display'
            ? '🖥️ Screen capture unavailable in this environment'
            : msg);
        }
        if (!resp.ok) {
          const detail = await resp.text().catch(() => '');
          throw new Error(detail || 'Desktop preview unavailable');
        }
        const blob = await resp.blob();
        if (this.desktopPreview.url && this.desktopPreview.url.startsWith('blob:')) {
          URL.revokeObjectURL(this.desktopPreview.url);
        }
        this.desktopPreview.url = URL.createObjectURL(blob);
        this.desktopPreview.lastUpdated = new Date().toISOString();
      } catch (e) {
        this.desktopPreview.error = e.message || 'Desktop preview unavailable';
      }
      this.desktopPreview.loading = false;
    },

    scheduleDesktopPreview() {
      if (this.desktopPreview.timer) clearTimeout(this.desktopPreview.timer);
      if (!this.desktopPreview.enabled || !(this.chatLoading || this.liveOperator.active)) return;
      this.desktopPreview.timer = setTimeout(async () => {
        await this.refreshDesktopPreview();
        this.scheduleDesktopPreview();
      }, this.desktopPreview.intervalMs || 8000);
    },

    stopDesktopPreview() {
      if (this.desktopPreview.timer) clearTimeout(this.desktopPreview.timer);
      this.desktopPreview.timer = null;
    },

    setAgentStage(phase) {
      if (this.agentLifecycle.includes(phase)) this.agentProgressState = phase;
    },

    toggleAgentMode(force = null) {
      this.agentMode = typeof force === 'boolean' ? force : !this.agentMode;
      if (this.agentMode && this.usesOllamaBackend() && this.ollamaModels.length === 0) {
        this.loadOllamaModels();
      }
    },

    clearChatInput() {
      this.chatInput = '';
      this.resetChatComposerHeight();
    },

    handleComposerEnter(event) {
      if (!event) return;
      if (event.isComposing || event.keyCode === 229) return;
      if (event.shiftKey) {
        requestAnimationFrame(() => this.resetChatComposerHeight());
        return;
      }
      event.preventDefault();
      this.sendChat();
    },

    resetChatComposerHeight() {
      this.$nextTick(() => {
        const ta = this.$refs.chatComposer;
        if (!ta) return;
        const baseHeight = this.isMobile ? 44 : 52;
        ta.style.height = baseHeight + 'px';
        if (this.chatInput.trim()) {
          ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
        }
      });
    },

    connectionBadgeClass(state) {
      const tone = String(state || '').toLowerCase();
      if (tone === 'offline') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      if (tone === 'reconnecting') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
      if (tone === 'domain_active') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (tone === 'tunnel_active') return 'border-blue-500/20 bg-blue-500/10 text-blue-200';
      return 'border-slate-700 bg-slate-950/60 text-slate-300';
    },

    connectionStatusBadges() {
      const badges = [];
      if (!this.serverConnected) {
        badges.push({ key: 'offline', label: 'Offline', state: 'offline' });
        return badges;
      }
      badges.push({ key: 'connected', label: 'Connected', state: 'domain_active' });
      if (this.liveFeed.reconnecting) badges.push({ key: 'reconnecting', label: 'Reconnecting', state: 'reconnecting' });
      const state = this.connectionState || {};
      if (state.domain_active) badges.push({ key: 'domain', label: 'Domain Active', state: 'domain_active' });
      else if (state.stable_domain_enabled) badges.push({ key: 'domain-set', label: 'Domain Set', state: 'reconnecting' });
      else if (state.tunnel_active) badges.push({ key: 'tunnel', label: 'Tunnel Active', state: 'tunnel_active' });
      else badges.push({ key: 'local', label: 'Local Only', state: 'local_only' });
      return badges;
    },

    terminalModeOptions() {
      return [
        { value: 'read_only', label: 'Read-only' },
        { value: 'approval_required', label: 'Approval required' },
        { value: 'simulation', label: 'Simulation' },
      ];
    },

    terminalStatusClass(status) {
      const value = String(status || '').toLowerCase();
      if (value === 'running') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (value === 'pending_approval') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
      if (value === 'failed' || value === 'stopped') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      return 'border-slate-700 bg-slate-950/60 text-slate-300';
    },

    setExternalProviderHint(value = '') {
      this.composerOptions.external_provider_hint = value || '';
      this.composerOptions.external_mode = value ? 'cloud_assist' : 'local_first';
    },

    setLocalOnly(enabled = true) {
      this.composerOptions.external_provider_hint = '';
      this.composerOptions.external_mode = enabled ? 'disable_external_calls' : 'local_first';
    },

    async toggleTerminalMode(force = null) {
      const enabled = typeof force === 'boolean' ? force : !this.composerOptions.terminal_mode;
      this.composerOptions.terminal_mode = enabled;
      this.terminal.panelOpen = enabled;
      if (!enabled) return;
      await this.loadTerminalSessions();
      await this.ensureTerminalSession();
    },

    toggleLiveDesktopFeed(force = null) {
      const enabled = typeof force === 'boolean' ? force : !this.composerOptions.live_desktop_feed;
      this.composerOptions.live_desktop_feed = enabled;
      this.desktopPreview.enabled = enabled;
      if (enabled) {
        this.refreshDesktopPreview(true);
        this.scheduleDesktopPreview();
      } else {
        this.stopDesktopPreview();
      }
    },

    currentTerminalSession() {
      const sessionId = Number(this.terminal.activeSessionId || 0);
      return (this.terminal.sessions || []).find(item => Number(item.id) === sessionId) || this.terminal.sessionDetail || null;
    },

    async loadTerminalSessions(selectId = null) {
      this.terminal.loading = true;
      try {
        const query = this.chatProjectId ? `?workspace_id=${encodeURIComponent(this.chatProjectId)}` : '';
        const rows = await this.api('GET', `/api/terminal/sessions${query}`);
        this.terminal.sessions = rows || [];
        const wanted = selectId || this.terminal.activeSessionId || rows?.[0]?.id || null;
        if (wanted) {
          this.terminal.activeSessionId = Number(wanted);
        }
      } catch (e) {
        this.showToast(`Terminal sessions failed: ${e.message}`);
      }
      this.terminal.loading = false;
    },

    async ensureTerminalSession() {
      if (this.terminal.activeSessionId) {
        await this.loadTerminalSessionDetail(this.terminal.activeSessionId, { silent: true });
        return;
      }
      await this.createTerminalSession();
    },

    async createTerminalSession() {
      this.terminal.loading = true;
      try {
        const created = await this.api('POST', '/api/terminal/sessions', {
          title: this.chatProject?.name ? `${this.chatProject.name} Terminal` : 'Console Terminal',
          workspace_id: this.chatProjectId ? parseInt(this.chatProjectId, 10) : null,
          mode: this.terminal.mode,
          cwd: this.chatProject?.path || null,
        });
        this.terminal.sessions = [created, ...(this.terminal.sessions || []).filter(item => Number(item.id) !== Number(created.id))];
        this.terminal.activeSessionId = Number(created.id);
        await this.loadTerminalSessionDetail(created.id);
      } catch (e) {
        this.showToast(`Terminal session failed: ${e.message}`);
      }
      this.terminal.loading = false;
    },

    async loadTerminalSessionDetail(sessionId, { silent = false } = {}) {
      if (!sessionId) return;
      if (!silent) this.terminal.detailLoading = true;
      try {
        const detail = await this.api('GET', `/api/terminal/sessions/${sessionId}`);
        this.terminal.sessionDetail = detail;
        this.terminal.activeSessionId = Number(detail.id);
        this.terminal.mode = detail.mode || this.terminal.mode;
        this.terminal.lastDetailLoadedAt = new Date().toISOString();
        const nextSessions = [...(this.terminal.sessions || [])];
        const idx = nextSessions.findIndex(item => Number(item.id) === Number(detail.id));
        if (idx >= 0) nextSessions[idx] = { ...nextSessions[idx], ...detail };
        else nextSessions.unshift(detail);
        this.terminal.sessions = nextSessions;
      } catch (e) {
        if (!silent) this.showToast(`Terminal detail failed: ${e.message}`);
      }
      if (!silent) this.terminal.detailLoading = false;
    },

    async executeTerminalCommand(approved = false) {
      const command = String(approved ? (this.terminal.pendingCommand || this.terminal.command) : this.terminal.command || '').trim();
      if (!command || this.terminal.executing) return;
      await this.ensureTerminalSession();
      if (!this.terminal.activeSessionId) return;
      this.terminal.executing = true;
      try {
        const endpoint = approved
          ? `/api/terminal/sessions/${this.terminal.activeSessionId}/approve`
          : `/api/terminal/sessions/${this.terminal.activeSessionId}/execute`;
        const result = await this.api('POST', endpoint, {
          command,
          mode: this.terminal.mode,
        });
        if (result.status === 'approval_required') {
          this.terminal.pendingCommand = result.command || command;
          this.terminal.approvalRequired = true;
          this.showToast('Approval required before Axon runs this command');
        } else if (result.status === 'blocked') {
          this.terminal.pendingCommand = '';
          this.terminal.approvalRequired = false;
          this.showToast(result.message || 'That command is blocked in read-only mode');
        } else if (result.status === 'simulation') {
          this.terminal.pendingCommand = '';
          this.terminal.approvalRequired = false;
          this.terminal.command = '';
          this.showToast(result.message || 'Simulation only');
        } else {
          this.terminal.pendingCommand = '';
          this.terminal.approvalRequired = false;
          this.terminal.command = '';
          this.showToast('Terminal command started');
        }
        await this.loadTerminalSessionDetail(this.terminal.activeSessionId, { silent: true });
      } catch (e) {
        this.showToast(`Terminal run failed: ${e.message}`);
      }
      this.terminal.executing = false;
    },

    async stopTerminalCommand() {
      if (!this.terminal.activeSessionId || this.terminal.stopping) return;
      this.terminal.stopping = true;
      try {
        const res = await this.api('POST', `/api/terminal/sessions/${this.terminal.activeSessionId}/stop`);
        this.showToast(res.message || 'Command stopped');
        await this.loadTerminalSessionDetail(this.terminal.activeSessionId, { silent: true });
      } catch (e) {
        this.showToast(`Stop failed: ${e.message}`);
      }
      this.terminal.stopping = false;
    },

    async connectLiveFeed() {
      if (!this.settingsForm.live_feed_enabled) {
        this.liveFeed.connected = false;
        this.liveFeed.connecting = false;
        this.liveFeed.reconnecting = false;
        this.liveFeed.error = '';
        return;
      }
      if (!this.authenticated || this.liveFeed.connecting) return;
      if (this.liveFeed.controller) {
        try { this.liveFeed.controller.abort(); } catch (_) {}
      }
      this.liveFeed.connecting = true;
      const controller = new AbortController();
      this.liveFeed.controller = controller;
      try {
        const resp = await fetch('/api/live/feed', {
          headers: this.authHeaders(),
          cache: 'no-store',
          signal: controller.signal,
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          return;
        }
        if (!resp.ok || !resp.body) {
          throw new Error(resp.statusText || 'Live feed unavailable');
        }
        this.liveFeed.connected = true;
        this.liveFeed.connecting = false;
        this.liveFeed.reconnecting = false;
        this.liveFeed.error = '';
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.type === 'heartbeat') {
                // Keep-alive — just update connection state
                this.liveFeed.connected = true;
                this.liveFeed.reconnecting = false;
                continue;
              }
              this.handleLiveFeedSnapshot(payload);
            } catch (_) {}
          }
        }
        throw new Error('Live feed disconnected');
      } catch (e) {
        if (controller.signal.aborted) return;
        this.liveFeed.connected = false;
        this.liveFeed.connecting = false;
        this.liveFeed.reconnecting = true;
        this.liveFeed.error = e.message || 'Live feed unavailable';
        setTimeout(() => this.connectLiveFeed(), 6000);
      }
    },

    handleLiveFeedSnapshot(payload) {
      this.liveFeed.latest = payload;
      this.liveFeed.connected = true;
      this.liveFeed.reconnecting = false;
      if (payload?.connection) this.connectionState = payload.connection;
      if (payload?.browser_actions) {
        this.browserActions = {
          ...this.browserActions,
          ...payload.browser_actions,
        };
      }
      if (Array.isArray(payload?.terminal?.sessions)) {
        this.terminal.sessions = payload.terminal.sessions;
      }
      const activeTerminalId = payload?.terminal?.active_session_id;
      if (activeTerminalId && Number(activeTerminalId) === Number(this.terminal.activeSessionId || 0)) {
        this.loadTerminalSessionDetail(activeTerminalId, { silent: true });
      }
      if (!this.dashRecentActivity.length && Array.isArray(payload?.activity) && payload.activity.length) {
        this.dashRecentActivity = payload.activity;
      }
    },

    async openResourcePicker() {
      this.showResourcePicker = !this.showResourcePicker;
      if (this.showResourcePicker) this.showComposerMenu = false;
      if (this.showResourcePicker && !this.resources.length) {
        await this.loadResources();
      }
      if (this.showResourcePicker && !this.researchPacks.length) {
        await this.loadResearchPacks();
      }
    },

    isResourceAttached(resourceId) {
      return this.selectedResources.some(resource => Number(resource.id) === Number(resourceId));
    },

    mergeSelectedResources(items = []) {
      const next = [...this.selectedResources];
      for (const item of items) {
        if (!item?.id || next.some(existing => Number(existing.id) === Number(item.id))) continue;
        next.push(item);
      }
      this.selectedResources = next;
    },

    toggleResourceAttachment(resource) {
      if (!resource?.id) return;
      if (this.isResourceAttached(resource.id)) {
        this.removeResourceAttachment(resource.id);
        return;
      }
      this.mergeSelectedResources([resource]);
    },

    removeResourceAttachment(resourceId) {
      this.selectedResources = this.selectedResources.filter(resource => Number(resource.id) !== Number(resourceId));
    },

    resourceChipLabel(resource) {
      return resource?.title || resource?.name || `Resource ${resource?.id || ''}`.trim();
    },

    resourceStatusClass(status) {
      const value = String(status || '').toLowerCase();
      if (value === 'ready') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
      if (value === 'processing') return 'border-blue-500/20 bg-blue-500/10 text-blue-200';
      if (value === 'failed') return 'border-rose-500/20 bg-rose-500/10 text-rose-300';
      return 'border-slate-700 bg-slate-950/60 text-slate-400';
    },

    resourceTrustClass(level) {
      const value = String(level || 'medium').toLowerCase();
      if (value === 'high') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300';
      if (value === 'low') return 'border-rose-500/20 bg-rose-500/10 text-rose-300';
      return 'border-amber-500/20 bg-amber-500/10 text-amber-300';
    },

    workspaceLabel(workspaceId) {
      const id = Number(workspaceId || 0);
      if (!id) return '';
      const match = (this.projects || []).find(project => Number(project.id) === id);
      return match?.name || '';
    },

    parseStoredChatMessage(content) {
      const raw = String(content || '');
      const match = raw.match(/\n\n\[Attached resources: ([^\]]+)\]\s*$/);
      if (!match) return { content: raw, resources: [] };
      const titles = match[1]
        .split(',')
        .map(item => item.trim())
        .filter(Boolean)
        .map((title, index) => ({ id: `history-${index}-${title}`, title }));
      return {
        content: raw.slice(0, match.index).trimEnd(),
        resources: titles,
      };
    },

    async loadResources(selectId = null) {
      this.resourcesLoading = true;
      try {
        const data = await this.api('GET', '/api/resources');
        this.resources = data.items || [];
        if (selectId) {
          const match = this.resources.find(resource => Number(resource.id) === Number(selectId));
          if (match) await this.viewResource(match);
        } else if (!this.resourceDetail && this.resources.length) {
          await this.viewResource(this.resources[0]);
        }
      } catch (e) {
        this.showToast(`Resources error: ${e.message}`);
      }
      this.resourcesLoading = false;
    },

    async handleResourceUpload(event) {
      const files = Array.from(event?.target?.files || []);
      if (!files.length || this.resourceUploading) return;
      this.resourceUploading = true;
      try {
        const form = new FormData();
        files.forEach(file => form.append('files', file));
        const resp = await fetch('/api/resources/upload', {
          method: 'POST',
          headers: this.authHeaders(),
          body: form,
        });
        if (resp.status === 401) {
          this.handleAuthRequired();
          throw new Error('Session expired');
        }
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || 'Upload failed');
        const items = data.items || [];
        await this.loadResources(items[0]?.id || null);
        this.mergeSelectedResources(items);
        this.showToast(items.length > 1 ? `${items.length} resources added` : 'Resource added');
      } catch (e) {
        this.showToast(`Upload failed: ${e.message}`);
      }
      this.resourceUploading = false;
      if (event?.target) event.target.value = '';
    },

    async importResourceUrl() {
      const url = this.resourceImportForm.url.trim();
      if (!url || this.resourceImporting) return;
      this.resourceImporting = true;
      try {
        const data = await this.api('POST', '/api/resources/import-url', {
          url,
          title: this.resourceImportForm.title.trim() || '',
        });
        if (data?.item) {
          await this.loadResources(data.item.id);
          this.mergeSelectedResources([data.item]);
          this.showToast('Resource imported');
        }
        this.resourceImportForm = { url: '', title: '' };
      } catch (e) {
        this.showToast(`Import failed: ${e.message}`);
      }
      this.resourceImporting = false;
    },

    async viewResource(resource) {
      if (!resource?.id) return;
      this.resourceDetailLoading = true;
      this.resourceDetail = null;
      this.resourceDetailContent = '';
      if (this.resourceDetailPreviewUrl?.startsWith('blob:')) {
        URL.revokeObjectURL(this.resourceDetailPreviewUrl);
      }
      this.resourceDetailPreviewUrl = '';
      try {
        this.resourceDetail = await this.api('GET', `/api/resources/${resource.id}`);
        if (String(this.resourceDetail.kind || '').toLowerCase() === 'image') {
          const resp = await fetch(`/api/resources/${resource.id}/content`, {
            headers: this.authHeaders(),
            cache: 'no-store',
          });
          if (resp.status === 401) {
            this.handleAuthRequired();
            throw new Error('Session expired');
          }
          if (!resp.ok) {
            const detail = await resp.text().catch(() => '');
            throw new Error(detail || 'Preview unavailable');
          }
          const blob = await resp.blob();
          this.resourceDetailPreviewUrl = URL.createObjectURL(blob);
        } else {
          const content = await this.api('GET', `/api/resources/${resource.id}/content`);
          this.resourceDetailContent = content.content || content.preview_text || '';
        }
      } catch (e) {
        this.showToast(`Resource preview failed: ${e.message}`);
      }
      this.resourceDetailLoading = false;
    },

    async useResourceInConsole(resource) {
      if (!resource?.id) return;
      this.mergeSelectedResources([resource]);
      if (String(resource.kind || '').toLowerCase() === 'image') {
        this.visionWarningDismissed = false;
      }
      this.activeTab = 'chat';
      this.showResourcePicker = false;
      this.showToast('Resource attached to the console');
    },

    async useResourceInDeepResearch(resource) {
      if (!resource?.id) return;
      this.setComposerOption('intelligence_mode', 'deep_research');
      this.mergeSelectedResources([resource]);
      if (String(resource.kind || '').toLowerCase() === 'image') {
        this.visionWarningDismissed = false;
      }
      this.activeTab = 'chat';
      this.showToast('Resource attached for Deep Research');
    },

    consoleHasImageAttachmentWithoutVision() {
      const hasImage = (this.selectedResources || []).some(resource => {
        const kind = String(resource?.kind || '').toLowerCase();
        const mime = String(resource?.mime_type || '').toLowerCase();
        return kind === 'image' || mime.startsWith('image/');
      });
      return hasImage && !this.runtimeStatus?.vision_status?.ready && !this.visionWarningDismissed;
    },

    async updateResourceMetadata(resourceId, payload, successMessage = 'Resource updated') {
      const updated = await this.api('PATCH', `/api/resources/${resourceId}`, payload);
      this.resources = this.resources.map(resource => Number(resource.id) === Number(updated.id) ? updated : resource);
      if (Number(this.resourceDetail?.id) === Number(updated.id)) {
        this.resourceDetail = { ...this.resourceDetail, ...updated };
      }
      this.selectedResources = this.selectedResources.map(resource => Number(resource.id) === Number(updated.id) ? { ...resource, ...updated } : resource);
      this.showToast(successMessage);
      return updated;
    },

    async setResourcePinned(resource, value) {
      if (!resource?.id) return;
      try {
        await this.updateResourceMetadata(resource.id, { pinned: !!value }, value ? 'Resource pinned' : 'Resource unpinned');
      } catch (e) {
        this.showToast(`Pin failed: ${e.message}`);
      }
    },

    async setResourceTrust(resource, value) {
      if (!resource?.id) return;
      try {
        await this.updateResourceMetadata(resource.id, { trust_level: value }, `Trust set to ${value}`);
      } catch (e) {
        this.showToast(`Trust update failed: ${e.message}`);
      }
    },

    async linkResourceToWorkspace(resource, workspaceId) {
      if (!resource?.id) return;
      const normalized = workspaceId ? Number(workspaceId) : null;
      try {
        const updated = await this.updateResourceMetadata(
          resource.id,
          { workspace_id: normalized },
          normalized ? 'Resource linked to workspace' : 'Workspace link removed'
        );
        if (normalized && !updated.workspace_name) {
          const label = this.workspaceLabel(normalized);
          if (label && Number(this.resourceDetail?.id) === Number(updated.id)) {
            this.resourceDetail.workspace_name = label;
          }
        }
      } catch (e) {
        this.showToast(`Workspace link failed: ${e.message}`);
      }
    },

    async reprocessResource(resource) {
      if (!resource?.id) return;
      try {
        this.resourceDetail = await this.api('POST', `/api/resources/${resource.id}/reprocess`);
        await this.loadResources(resource.id);
        this.showToast('Resource reprocessed');
      } catch (e) {
        this.showToast(`Reprocess failed: ${e.message}`);
      }
    },

    async deleteResource(resource) {
      if (!resource?.id) return;
      if (!confirm(`Delete resource "${this.resourceChipLabel(resource)}"?`)) return;
      try {
        await this.api('DELETE', `/api/resources/${resource.id}`);
        this.removeResourceAttachment(resource.id);
        if (Number(this.resourceDetail?.id) === Number(resource.id)) {
          this.resourceDetail = null;
          this.resourceDetailContent = '';
          if (this.resourceDetailPreviewUrl?.startsWith('blob:')) {
            URL.revokeObjectURL(this.resourceDetailPreviewUrl);
          }
          this.resourceDetailPreviewUrl = '';
        }
        await this.loadResources();
        this.showToast('Resource deleted');
      } catch (e) {
        this.showToast(`Delete failed: ${e.message}`);
      }
    },

    shouldAutoUseAgent(msg) {
      const text = (msg || '').trim();
      if (!text || !this.usesOllamaBackend()) return false;
      const lower = text.toLowerCase();
      const explainers = ['how do i', 'how can i', 'what is', 'why is', 'explain', 'teach me'];
      if (explainers.some(prefix => lower.startsWith(prefix))) return false;
      const actionable = [
        'list ', 'show ', 'open ', 'read ', 'find ', 'search ', 'scan ', 'inspect ',
        'check ', 'look at ', 'run ', 'execute ', 'desktop', 'folder', 'folders',
        'directory', 'directories', 'file ', 'files ', 'repo', 'repository',
        'branch', 'commit', 'todo', 'git status', 'git log', 'pwd', 'ls ',
      ];
      return actionable.some(phrase => lower.includes(phrase)) ||
        /(^|\s)(~\/|\/home\/|package\.json|readme|\.ts\b|\.tsx\b|\.js\b|\.py\b|\.md\b)/i.test(text);
    },

    resolveChatMode(msg) {
      const preferred = this.composerPreferredMode(msg);
      if (preferred) return preferred;
      return this.agentMode || this.shouldAutoUseAgent(msg) ? 'agent' : 'chat';
    },

    createAssistantPlaceholder(respId, mode, retryResources = []) {
      return {
        id: respId,
        role: 'assistant',
        content: '',
        streaming: true,
        created_at: new Date().toISOString(),
        mode,
        modelLabel: this.assistantRuntimeLabel(),
        agentEvents: mode === 'agent' ? [] : undefined,
        retryResources,
      };
    },

    async streamChatMessage(msg, mode, respId, resourceIds = []) {
      const endpoint = mode === 'agent' ? '/api/agent' : '/api/chat/stream';
      const payload = {
        message: msg,
        project_id: this.chatProjectId ? parseInt(this.chatProjectId) : null,
        resource_ids: resourceIds,
        composer_options: this.normalizedComposerOptions(),
      };
      if (this.usesOllamaBackend()) payload.model = this.activeChatModel() || '';

      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: this.authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
      });

      if (resp.status === 401) {
        this.handleAuthRequired();
        this.updateLiveOperator(mode, { type: 'error', message: 'Session expired.' });
        throw new Error('Session expired');
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        this.updateLiveOperator(mode, { type: 'error', message: err.detail || resp.statusText });
        throw new Error(err.detail || resp.statusText);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      if (mode === 'agent') {
        this.setAgentStage('plan');
        this.updateLiveOperator(mode, { type: 'text' });
      } else {
        this.updateLiveOperator(mode, { chunk: 'stream-open' });
      }

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
            const idx = this.chatMessages.findIndex(m => m.id === respId);
            if (idx < 0) continue;

            if (mode === 'agent') {
              if (data.type === 'text') {
                if (this.chatMessages[idx].agentEvents?.length) this.setAgentStage('verify');
                this.chatMessages[idx].content += data.chunk;
                this.updateLiveOperator(mode, data);
                this.scrollChat();
              } else if (data.type === 'tool_call' || data.type === 'tool_result') {
                this.setAgentStage(data.type === 'tool_call' ? 'execute' : 'verify');
                this.chatMessages[idx].agentEvents.push(data);
                this.updateLiveOperator(mode, data);
                this.scrollChat();
              } else if (data.type === 'done') {
                this.setAgentStage('verify');
                this.chatMessages[idx].streaming = false;
                this.updateLiveOperator(mode, data);
              } else if (data.type === 'error') {
                this.setAgentStage('recover');
                this.chatMessages[idx].content += `\n⚠️ ${data.message}`;
                this.chatMessages[idx].streaming = false;
                this.chatMessages[idx].error = true;
                this.chatMessages[idx].retryMsg = msg;
                this.updateLiveOperator(mode, data);
              }
            } else {
              if (data.chunk) {
                this.chatMessages[idx].content += data.chunk;
                this.updateLiveOperator(mode, data);
                this.scrollChat();
              }
              if (data.done) {
                this.chatMessages[idx].streaming = false;
                this.updateLiveOperator(mode, data);
              }
              if (data.error) {
                this.chatMessages[idx].content += `\n⚠️ ${data.error}`;
                this.chatMessages[idx].streaming = false;
                this.chatMessages[idx].error = true;
                this.chatMessages[idx].retryMsg = msg;
                this.updateLiveOperator(mode, { error: data.error });
              }
            }
          } catch(_) {}
        }
      }

      const idx = this.chatMessages.findIndex(m => m.id === respId);
      if (idx >= 0) {
        this.chatMessages[idx].streaming = false;
        this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
      }
      this.clearLiveOperator(this.liveOperator.phase === 'recover' ? 4200 : 1400);
    },

  };
}

window.axonDashboardMixin = axonDashboardMixin;
