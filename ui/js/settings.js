/* ══════════════════════════════════════════════════════════════
   Axon — Settings Module
   ══════════════════════════════════════════════════════════════ */

function axonSettingsMixin() {
  return {

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
          api_provider: s.api_provider || 'anthropic',
          claude_cli_path: s.claude_cli_path || '',
          ollama_url: s.ollama_url || '',
          ollama_runtime_mode: s.ollama_runtime_mode || 'gpu_default',
          ollama_model: s.ollama_model || '',
          code_model: s.code_model || s.ollama_model || '',
          general_model: s.general_model || '',
          reasoning_model: s.reasoning_model || '',
          embeddings_model: s.embeddings_model || '',
          vision_model: s.vision_model || '',
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
          azure_voice: s.azure_voice || 'en-ZA-LeahNeural',
          local_stt_model: s.local_stt_model || 'base',
          local_stt_language: s.local_stt_language || 'en',
          local_tts_model_path: s.local_tts_model_path || '',
          local_tts_config_path: s.local_tts_config_path || '',
          _azureSpeechKeyHint: '',
          _cloudflareTunnelTokenHint: '',
          _deepseekKeyHint: '',
        };
        this.selectedChatModel = s.code_model || s.ollama_model || this.selectedChatModel || '';
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
      payload.api_provider = this.settingsForm.api_provider || 'anthropic';
      payload.claude_cli_path = this.settingsForm.claude_cli_path || '';
      payload.ollama_url = this.settingsForm.ollama_url || '';
      payload.ollama_runtime_mode = this.settingsForm.ollama_runtime_mode || 'gpu_default';
      payload.ollama_model = this.settingsForm.ollama_model || '';
      payload.code_model = this.settingsForm.code_model || '';
      payload.general_model = this.settingsForm.general_model || '';
      payload.reasoning_model = this.settingsForm.reasoning_model || '';
      payload.embeddings_model = this.settingsForm.embeddings_model || '';
      payload.vision_model = this.settingsForm.vision_model || '';
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
      payload.azure_voice = this.settingsForm.azure_voice || 'en-ZA-LeahNeural';
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
        await this.api('POST', '/api/settings', { api_provider: this.settingsForm.api_provider || 'anthropic' });
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

  };
}

window.axonSettingsMixin = axonSettingsMixin;
