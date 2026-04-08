/* ══════════════════════════════════════════════════════════════
   Axon — Settings Module
   ══════════════════════════════════════════════════════════════ */

function axonSettingsMixin() {
  return {
    // ── Console zoom state ─────────────────────────────────────────
    _consoleZoom: 1.0,
    vaultUnlocked: false,
    vaultProviderKeys: {},

    consoleZoomPercent() {
      return Math.round((this._consoleZoom || 1) * 100) + '%';
    },
    adjustConsoleZoom(delta) {
      this._consoleZoom = Math.min(2, Math.max(0.5, (this._consoleZoom || 1) + delta));
      document.documentElement.style.setProperty('--console-zoom', this._consoleZoom);
    },
    resetConsoleZoom() {
      this._consoleZoom = 1.0;
      document.documentElement.style.setProperty('--console-zoom', '1');
    },

    currentRuntimeBackend() {
      const explicit = String(this.settingsForm?.ai_backend || '').trim().toLowerCase();
      if (explicit) return explicit;
      const label = String(this.runtimeStatus?.runtime_label || '').toLowerCase();
      if (label.includes('cli') || label.includes('codex') || label.includes('claude')) return 'cli';
      if (label.includes('ollama') || label.includes('local')) return 'ollama';
      if (this.runtimeStatus?.cli_runtime || this.runtimeStatus?.cli_model) return 'cli';
      if (this.runtimeStatus?.ollama_runtime_mode) return 'ollama';
      return 'api';
    },
    currentBackendSupportsAgent() {
      const backend = this.currentRuntimeBackend?.() || '';
      return backend === 'ollama' || backend === 'cli';
    },
    usesOllamaBackend() {
      const backend = this.currentRuntimeBackend?.() || '';
      return backend === 'ollama' || backend === 'cli';
    },
    activeChatModel() {
      const backend = this.currentRuntimeBackend?.() || '';
      if (backend === 'cli') {
        return String(
          this.settingsForm?.cli_runtime_model
          || this.runtimeStatus?.cli_model
          || this.runtimeStatus?.active_model
          || ''
        ).trim();
      }
      if (backend === 'api') {
        return String(this.selectedApiProviderModel?.() || this.runtimeStatus?.active_model || '').trim();
      }
      return String(
        this.selectedChatModel
        || this.settingsForm?.code_model
        || this.settingsForm?.ollama_model
        || ''
      ).trim();
    },
    assistantRuntimeLabel() {
      const backend = this.currentRuntimeBackend?.() || '';
      if (backend === 'cli') {
        return this.activeChatModel?.() || 'CLI Agent';
      }
      if (backend === 'ollama') {
        return this.activeChatModel?.() || 'Local model';
      }
      if (backend === 'api') {
        const provider = this.selectedApiProviderLabel?.() || '';
        const model = this.selectedApiProviderModel?.() || '';
        return model ? `${provider} · ${model}` : provider || 'Cloud';
      }
      return this.activeChatModel?.() || 'Runtime';
    },
    async loadSettings() {
      try {
        const s = await this.api('GET', '/api/settings');
        this.settingsForm = {
          anthropic_api_key: '',  // always blank, let user re-enter
          anthropic_base_url: s.anthropic_base_url || '',
          anthropic_api_model: s.anthropic_api_model || '',
          projects_root: s.projects_root || '~/Desktop',
          scan_interval_hours: s.scan_interval_hours || '6',
          morning_digest_hour: s.morning_digest_hour || '8',
          ai_backend: s.ai_backend || 'ollama',
          api_provider: s.api_provider || 'deepseek',
          cli_runtime_path: s.cli_runtime_path || s.claude_cli_path || '',
          cli_runtime_model: s.cli_runtime_model || s.claude_cli_model || '',
          claude_cli_session_persistence_enabled: this.settingEnabled(s.claude_cli_session_persistence_enabled ?? true),
          ollama_url: s.ollama_url || '',
          ollama_runtime_mode: s.ollama_runtime_mode || 'gpu_default',
          ollama_model: s.ollama_model || '',
          code_model: s.code_model || s.ollama_model || '',
          general_model: s.general_model || '',
          reasoning_model: s.reasoning_model || '',
          embeddings_model: s.embeddings_model || '',
          vision_model: s.vision_model || '',
          resource_fetch_proxy: s.resource_fetch_proxy || '',
          resource_storage_path: s.resource_storage_path || '~/.devbrain/resources',
          resource_upload_max_mb: s.resource_upload_max_mb || '20',
          resource_url_import_enabled: this.settingEnabled(s.resource_url_import_enabled ?? true),
          live_feed_enabled: this.settingEnabled(s.live_feed_enabled ?? true),
          stable_domain_enabled: this.settingEnabled(s.stable_domain_enabled),
          stable_domain: s.stable_domain || 'axon.edudashpro.org.za',
          public_base_url: s.public_base_url || `https://${s.stable_domain || 'axon.edudashpro.org.za'}`,
          tunnel_mode: s.tunnel_mode || 'trycloudflare',
          cloudflare_tunnel_token: '',
          terminal_default_mode: s.terminal_default_mode || 'read_only',
          terminal_command_timeout_seconds: s.terminal_command_timeout_seconds || '25',
          cloud_agents_enabled: this.settingEnabled(s.cloud_agents_enabled),
          openai_gpts_enabled: this.settingEnabled(s.openai_gpts_enabled),
          gemini_gems_enabled: this.settingEnabled(s.gemini_gems_enabled),
          openai_api_key: '',
          openai_base_url: s.openai_base_url || '',
          openai_api_model: s.openai_api_model || '',
          gemini_api_key: '',
          gemini_base_url: s.gemini_base_url || '',
          gemini_api_model: s.gemini_api_model || '',
          deepseek_api_key: '',
          deepseek_base_url: s.deepseek_base_url || '',
          deepseek_api_model: s.deepseek_api_model || '',
          github_token: '',   // never pre-fill secrets
          slack_webhook_url: s.slack_webhook_url || '',
          webhook_urls: s.webhook_urls || '',
          webhook_secret: '',  // never pre-fill
          azure_speech_key: '',  // never pre-fill secrets
          azure_speech_region: s.azure_speech_region || 'eastus',
          azure_voice: s.azure_voice || 'en-ZA-LukeNeural',
          voice_speech_rate: s.voice_speech_rate || '0.85',
          voice_speech_pitch: s.voice_speech_pitch || '1.04',
          voice_attention_enabled: this.settingEnabled(s.voice_attention_enabled ?? true),
          voice_attention_autowake: this.settingEnabled(s.voice_attention_autowake ?? true),
          local_stt_model: s.local_stt_model || 'base',
          local_stt_language: s.local_stt_language || 'en',
          local_tts_model_path: s.local_tts_model_path || '',
          local_tts_config_path: s.local_tts_config_path || '',
          _azureSpeechKeyHint: '',
          _cloudflareTunnelTokenHint: '',
          _deepseekKeyHint: '',
          max_agent_iterations: s.max_agent_iterations || '75',
          context_compact_enabled: this.settingEnabled(s.context_compact_enabled ?? true),
          autonomy_profile: ['manual', 'workspace_auto', 'branch_auto', 'pr_auto'].includes(String(s.autonomy_profile || '').trim())
            ? s.autonomy_profile
            : 'workspace_auto',
          runtime_permissions_mode: ['default', 'ask_first', 'full_access'].includes(String(s.runtime_permissions_mode || '').trim())
            ? s.runtime_permissions_mode
            : (String(s.autonomy_profile || '').trim() === 'manual' ? 'ask_first' : 'default'),
          memory_first_enabled: this.settingEnabled(s.memory_first_enabled ?? true),
          external_fetch_policy: (s.external_fetch_policy === 'live_first') ? 'live_first' : 'cache_first',
          quick_model: s.quick_model || '',
          standard_model: s.standard_model || '',
          deep_model: s.deep_model || '',
          workspace_snapshot_ttl_seconds: s.workspace_snapshot_ttl_seconds || '60',
          memory_query_cache_ttl_seconds: s.memory_query_cache_ttl_seconds || '45',
          external_fetch_cache_ttl_seconds: s.external_fetch_cache_ttl_seconds || '21600',
          max_history_turns: s.max_history_turns || s.max_chat_history || '10',
        };
        this.selectedChatModel = s.code_model || s.ollama_model || this.selectedChatModel || '';
        this.syncPermissionChrome?.();
        if (s.ai_backend === 'ollama') { this.checkOllamaStatus(); this.loadOllamaModels(); }
        this.loadSystemActions();
        if (s.api_key_set) {
          this.settingsForm._keyHint = s.anthropic_api_key;
        }
        this.settingsForm._anthropicKeyHint = s.anthropic_api_key_set ? s.anthropic_api_key : '';
        this.settingsForm._openaiKeyHint = s.openai_api_key_set ? s.openai_api_key : '';
        this.settingsForm._geminiKeyHint = s.gemini_api_key_set ? s.gemini_api_key : '';
        this.settingsForm._deepseekKeyHint = s.deepseek_api_key_set ? s.deepseek_api_key : '';
        this.settingsForm._azureSpeechKeyHint = s.azure_speech_key_set ? s.azure_speech_key : '';
        this.settingsForm._cloudflareTunnelTokenHint = s.cloudflare_tunnel_token_set ? s.cloudflare_tunnel_token : '';
        if (s.github_token_set) {
          this.settingsForm._githubTokenHint = s.github_token;
        } else {
          this.settingsForm._githubTokenHint = '';
        }
        if (!this.settingsForm.live_feed_enabled && this.liveFeed.controller) {
          try { this.liveFeed.controller.abort(); } catch (_) {}
          this.liveFeed.connected = false;
          this.liveFeed.reconnecting = false;
          this.liveFeed.connecting = false;
        } else if (this.settingsForm.live_feed_enabled && this.authenticated) {
          this.connectLiveFeed();
        }
        this.loadTtsVoices(true);
        this.refreshVoiceCapability();
        this.refreshVaultProviderKeys();
      } catch(e) {}
    },
    async refreshVaultProviderKeys() {
      try {
        const r = await this.api('GET', '/api/vault/provider-keys');
        this.vaultUnlocked = !!r.unlocked;
        this.vaultProviderKeys = r.resolved || {};
      } catch(e) {
        this.vaultUnlocked = false;
        this.vaultProviderKeys = {};
      }
    },
    async saveSettings() {
      this.settingsSaving = true;
      this.settingsSaved = false;
      const payload = {};
      if (this.settingsForm.anthropic_api_key) payload.anthropic_api_key = this.settingsForm.anthropic_api_key;
      payload.anthropic_base_url = this.settingsForm.anthropic_base_url || '';
      payload.anthropic_api_model = this.settingsForm.anthropic_api_model || '';
      if (this.settingsForm.projects_root) payload.projects_root = this.settingsForm.projects_root;
      if (this.settingsForm.scan_interval_hours) payload.scan_interval_hours = String(this.settingsForm.scan_interval_hours);
      if (this.settingsForm.morning_digest_hour) payload.morning_digest_hour = String(this.settingsForm.morning_digest_hour);
      if (this.settingsForm.ai_backend) payload.ai_backend = this.settingsForm.ai_backend;
      payload.api_provider = this.settingsForm.api_provider || 'deepseek';
      payload.cli_runtime_path = this.settingsForm.cli_runtime_path || '';
      payload.cli_runtime_model = this.settingsForm.cli_runtime_model || '';
      payload.claude_cli_session_persistence_enabled = !!this.settingsForm.claude_cli_session_persistence_enabled;
      payload.ollama_url = this.settingsForm.ollama_url || '';
      payload.ollama_runtime_mode = this.settingsForm.ollama_runtime_mode || 'gpu_default';
      payload.ollama_model = this.settingsForm.ollama_model || '';
      payload.code_model = this.settingsForm.code_model || '';
      payload.general_model = this.settingsForm.general_model || '';
      payload.reasoning_model = this.settingsForm.reasoning_model || '';
      payload.embeddings_model = this.settingsForm.embeddings_model || '';
      payload.vision_model = this.settingsForm.vision_model || '';
      payload.resource_fetch_proxy = this.settingsForm.resource_fetch_proxy || '';
      payload.resource_storage_path = this.settingsForm.resource_storage_path || '~/.devbrain/resources';
      payload.resource_upload_max_mb = String(this.settingsForm.resource_upload_max_mb || '20');
      payload.resource_url_import_enabled = !!this.settingsForm.resource_url_import_enabled;
      payload.live_feed_enabled = !!this.settingsForm.live_feed_enabled;
      payload.stable_domain_enabled = !!this.settingsForm.stable_domain_enabled;
      payload.stable_domain = this.settingsForm.stable_domain || 'axon.edudashpro.org.za';
      payload.public_base_url = this.settingsForm.public_base_url || `https://${this.settingsForm.stable_domain || 'axon.edudashpro.org.za'}`;
      payload.tunnel_mode = this.settingsForm.tunnel_mode || 'trycloudflare';
      if (this.settingsForm.cloudflare_tunnel_token) payload.cloudflare_tunnel_token = this.settingsForm.cloudflare_tunnel_token;
      payload.terminal_default_mode = this.settingsForm.terminal_default_mode || 'read_only';
      payload.terminal_command_timeout_seconds = String(this.settingsForm.terminal_command_timeout_seconds || '25');
      payload.max_agent_iterations = String(this.settingsForm.max_agent_iterations || '75');
      payload.context_compact_enabled = !!this.settingsForm.context_compact_enabled;
      payload.autonomy_profile = ['manual', 'workspace_auto', 'branch_auto', 'pr_auto'].includes(this.settingsForm.autonomy_profile)
        ? this.settingsForm.autonomy_profile
        : 'workspace_auto';
      payload.runtime_permissions_mode = ['default', 'ask_first', 'full_access'].includes(String(this.settingsForm.runtime_permissions_mode || '').trim())
        ? this.settingsForm.runtime_permissions_mode
        : 'default';
      payload.memory_first_enabled = !!this.settingsForm.memory_first_enabled;
      payload.external_fetch_policy = this.settingsForm.external_fetch_policy === 'live_first' ? 'live_first' : 'cache_first';
      payload.quick_model = this.settingsForm.quick_model || '';
      payload.standard_model = this.settingsForm.standard_model || '';
      payload.deep_model = this.settingsForm.deep_model || '';
      payload.workspace_snapshot_ttl_seconds = String(this.settingsForm.workspace_snapshot_ttl_seconds || '60');
      payload.memory_query_cache_ttl_seconds = String(this.settingsForm.memory_query_cache_ttl_seconds || '45');
      payload.external_fetch_cache_ttl_seconds = String(this.settingsForm.external_fetch_cache_ttl_seconds || '21600');
      payload.max_history_turns = String(this.settingsForm.max_history_turns || '10');
      payload.cloud_agents_enabled = !!this.settingsForm.cloud_agents_enabled;
      payload.openai_gpts_enabled = !!this.settingsForm.openai_gpts_enabled;
      payload.gemini_gems_enabled = !!this.settingsForm.gemini_gems_enabled;
      if (this.settingsForm.openai_api_key) payload.openai_api_key = this.settingsForm.openai_api_key;
      payload.openai_base_url = this.settingsForm.openai_base_url || '';
      payload.openai_api_model = this.settingsForm.openai_api_model || '';
      if (this.settingsForm.gemini_api_key) payload.gemini_api_key = this.settingsForm.gemini_api_key;
      payload.gemini_base_url = this.settingsForm.gemini_base_url || '';
      payload.gemini_api_model = this.settingsForm.gemini_api_model || '';
      if (this.settingsForm.deepseek_api_key) payload.deepseek_api_key = this.settingsForm.deepseek_api_key;
      payload.deepseek_base_url = this.settingsForm.deepseek_base_url || '';
      payload.deepseek_api_model = this.settingsForm.deepseek_api_model || '';
      if (this.settingsForm.github_token) payload.github_token = this.settingsForm.github_token;
      payload.slack_webhook_url = this.settingsForm.slack_webhook_url || '';
      payload.webhook_urls = this.settingsForm.webhook_urls || '';
      if (this.settingsForm.webhook_secret) payload.webhook_secret = this.settingsForm.webhook_secret;
      if (this.settingsForm.azure_speech_key) payload.azure_speech_key = this.settingsForm.azure_speech_key;
      payload.azure_speech_region = this.settingsForm.azure_speech_region || 'eastus';
      payload.azure_voice = this.settingsForm.azure_voice || 'en-ZA-LukeNeural';
      payload.voice_speech_rate = String(this.settingsForm.voice_speech_rate || '0.85');
      payload.voice_speech_pitch = String(this.settingsForm.voice_speech_pitch || '1.04');
      payload.voice_attention_enabled = !!this.settingsForm.voice_attention_enabled;
      payload.voice_attention_autowake = !!this.settingsForm.voice_attention_autowake;
      payload.local_stt_model = this.settingsForm.local_stt_model || 'base';
      payload.local_stt_language = this.settingsForm.local_stt_language || 'en';
      payload.local_tts_model_path = this.settingsForm.local_tts_model_path || '';
      payload.local_tts_config_path = this.settingsForm.local_tts_config_path || '';
      try {
        await this.api('POST', '/api/settings', payload);
        this.updateProviderKeyHint('anthropic');
        this.updateProviderKeyHint('openai_gpts');
        this.updateProviderKeyHint('gemini_gems');
        this.updateProviderKeyHint('deepseek');
        this.updateProviderKeyHint('generic_api');
        if (this.settingsForm.azure_speech_key) {
          const raw = this.settingsForm.azure_speech_key;
          this.settingsForm._azureSpeechKeyHint = raw.length > 10 ? `${raw.slice(0, 4)}...${raw.slice(-4)}` : 'set';
          this.settingsForm.azure_speech_key = '';
        }
        if (this.settingsForm.cloudflare_tunnel_token) {
          const raw = this.settingsForm.cloudflare_tunnel_token;
          this.settingsForm._cloudflareTunnelTokenHint = raw.length > 10 ? `${raw.slice(0, 4)}...${raw.slice(-4)}` : 'set';
          this.settingsForm.cloudflare_tunnel_token = '';
        }
        if (this.settingsForm.github_token) {
          const raw = this.settingsForm.github_token;
          this.settingsForm._githubTokenHint = raw.length > 10 ? `${raw.slice(0, 4)}...${raw.slice(-4)}` : 'set';
          this.settingsForm.github_token = '';
        }
        this.refreshVoiceCapability();
        await this.loadVoiceStatus(true);
        this.syncChatModel(this.settingsForm.code_model || this.settingsForm.ollama_model || this.selectedChatModel);
        await this.loadTtsVoices(true);
        this.settingsSaved = true;
        await this.loadRuntimeStatus();
        if (this.settingsForm.live_feed_enabled) {
          this.connectLiveFeed();
        } else if (this.liveFeed.controller) {
          try { this.liveFeed.controller.abort(); } catch (_) {}
          this.liveFeed.connected = false;
          this.liveFeed.reconnecting = false;
          this.liveFeed.connecting = false;
        }
        setTimeout(() => this.settingsSaved = false, 3000);
      } catch(e) { this.showToast('Failed to save'); }
      this.settingsSaving = false;
    },
    async saveSettingsQuiet() {
      try {
        await this.api('POST', '/api/settings', { api_provider: this.settingsForm.api_provider || 'deepseek' });
        await this.loadRuntimeStatus();
      } catch(e) { this.showToast('Failed to switch provider'); }
    },
    async loadSystemActions() {
      this.systemActionsLoading = true;
      try {
        const data = await this.api('GET', '/api/system/actions');
        this.systemStatus = {
          host: data.host || {},
          services: data.services || { devbrain: {}, ollama: {} },
          actions: data.actions || [],
          error: '',
        };
      } catch(e) {
        this.systemStatus = {
          host: {},
          services: { devbrain: {}, ollama: {} },
          actions: [],
          error: e.message || 'System actions unavailable',
        };
      }
      this.systemActionsLoading = false;
    },
    openSystemAction(action) {
      if (!action || !action.supported) return;
      this.systemActionModal = {
        open: true,
        action,
        confirm: '',
        acknowledged: false,
        submitting: false,
        result: null,
      };
    },
    closeSystemAction() {
      this.systemActionModal = {
        open: false,
        action: null,
        confirm: '',
        acknowledged: false,
        submitting: false,
        result: null,
      };
    },
    async executeSystemAction() {
      const action = this.systemActionModal.action;
      if (!action || this.systemActionModal.submitting) return;
      this.systemActionModal.submitting = true;
      this.systemActionModal.result = null;
      try {
        const res = await this.api('POST', '/api/system/actions/execute', {
          action: action.id,
          confirmation_text: this.systemActionModal.confirm,
          acknowledge: this.systemActionModal.acknowledged,
        });
        this.systemActionModal.result = res;

        if (res.status === 'accepted') {
          this.serverConnected = false;
          this.showToast(res.message || `${action.title} queued`);
          setTimeout(() => window.location.reload(), res.reconnect_after_ms || 4500);
        } else if (res.status === 'completed') {
          this.showToast(res.message || `${action.title} completed`);
        } else if (res.status === 'manual_required') {
          this.showToast('Command prepared');
        }

        if (action.id === 'restart_ollama') {
          await this.checkOllamaStatus();
          await this.loadSystemActions();
          if (this.usesOllamaBackend()) this.loadOllamaModels();
        }
      } catch(e) {
        this.systemActionModal.result = {
          status: 'error',
          message: e.message || 'System action failed',
          command_preview: action.command_preview || '',
        };
      }
      this.systemActionModal.submitting = false;
    },

    // ── Connection health ───────────────────────────────────────
    async pollConnection() {
      try {
        const r = await fetch('/api/health', { signal: AbortSignal.timeout(5000) });
        this.serverConnected = r.ok;
      } catch(e) {
        this.serverConnected = false;
      }
      setTimeout(() => this.pollConnection(), 10000);
    },

    async reconnect() {
      this.reconnecting = true;
      try {
        const r = await fetch('/api/health', { signal: AbortSignal.timeout(8000) });
        this.serverConnected = r.ok;
        if (r.ok) {
          this.showToast('Reconnected \u2714');
          // Reload data after reconnect
          this.loadProjects();
          this.loadTasks();
          this.loadRuntimeStatus();
          this.connectLiveFeed();
          if (this.activeTab === 'chat') this.loadChatHistory();
          // JARVIS-style greeting on reconnect
          if (typeof this.onAxonReconnected === 'function') this.onAxonReconnected();
        } else {
          this.showToast('Server not reachable');
        }
      } catch(e) {
        this.serverConnected = false;
        this.showToast('Cannot reach server \u2014 check tunnel or WiFi');
      }
      this.reconnecting = false;
    },

    // ── Usage ──────────────────────────────────────────────────────
    async pollUsage() {
      try { this.usage = await this.api('GET', '/api/usage'); } catch(e) {}
      setTimeout(() => this.pollUsage(), 15000);  // refresh every 15s
    },

    syncPermissionChrome() {
      if (typeof document === 'undefined') return;
      const fullAccess = this.permissionPresetKey() === 'full_access';
      document.documentElement?.classList?.toggle('axon-full-access', fullAccess);
      document.body?.classList?.toggle('axon-full-access', fullAccess);
    },
    permissionPresetKey() {
      const mode = String(this.settingsForm?.runtime_permissions_mode || '').trim().toLowerCase();
      if (mode === 'ask_first' || mode === 'full_access') return mode;
      return String(this.settingsForm?.autonomy_profile || '').trim() === 'manual' ? 'ask_first' : 'default';
    },

    permissionPresetLabel() {
      const key = this.permissionPresetKey();
      if (key === 'full_access') return 'Full access';
      if (key === 'ask_first') return 'Ask first';
      return 'Default permissions';
    },

    permissionPresetMeta() {
      const key = this.permissionPresetKey();
      if (key === 'full_access') return 'Unsandboxed runtime with automatic command execution';
      if (key === 'ask_first') return 'Every protected action pauses for review';
      return 'Workspace-safe autonomy with exact approvals';
    },

    permissionPresetOptions() {
      return [
        {
          id: 'default',
          label: 'Default permissions',
          detail: 'Workspace-safe autonomy with exact approvals',
          locked: false,
        },
        {
          id: 'ask_first',
          label: 'Ask first',
          detail: 'Pause before protected work and keep Axon tightly gated',
          locked: false,
        },
        {
          id: 'full_access',
          label: 'Full access',
          detail: 'Codex has full access over your computer. Elevated risk.',
          locked: false,
        },
      ];
    },

    permissionPresetOptionClass(option = {}) {
      const active = this.permissionPresetKey() === option.id;
      if (active) {
        return option.id === 'full_access'
          ? 'border-rose-500/30 bg-rose-500/10 text-rose-100'
          : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
      }
      return option.id === 'full_access'
        ? 'border-rose-500/15 bg-rose-950/30 text-rose-200 hover:border-rose-400/35 hover:text-rose-100'
        : 'border-slate-800/80 bg-slate-900/55 text-slate-300 hover:border-slate-600 hover:text-white';
    },

    async setPermissionPreset(preset) {
      const normalized = String(preset || '').trim().toLowerCase();
      if (normalized === 'full_access') {
        const confirmed = window.confirm(
          'Enable Full access for Axon? This removes the normal exact-approval gate and lets the runtime operate without sandboxing. Only use this on a machine you trust.',
        );
        if (!confirmed) return;
      }
      const autonomyProfile = normalized === 'ask_first' ? 'manual' : 'workspace_auto';
      try {
        await this.api('POST', '/api/settings', {
          autonomy_profile: autonomyProfile,
          runtime_permissions_mode: normalized === 'full_access' ? 'full_access' : (normalized === 'ask_first' ? 'ask_first' : 'default'),
        });
        this.settingsForm.autonomy_profile = autonomyProfile;
        this.settingsForm.runtime_permissions_mode = normalized === 'full_access' ? 'full_access' : (normalized === 'ask_first' ? 'ask_first' : 'default');
        this.permissionPresetOpen = false;
        this.syncPermissionChrome?.();
        await this.loadRuntimeStatus();
        this.showToast(
          normalized === 'full_access'
            ? 'Axon full access enabled'
            : normalized === 'ask_first'
            ? 'Axon will ask before protected work'
            : 'Axon is back on default permissions',
        );
      } catch (e) {
        this.showToast(`Failed to change permissions: ${e.message || e}`);
      }
    },

  };
}

window.axonSettingsMixin = axonSettingsMixin;
