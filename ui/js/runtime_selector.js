/* ══════════════════════════════════════════════════════════════
   Axon — Runtime selector module
   ══════════════════════════════════════════════════════════════ */

function axonRuntimeSelectorMixin() {
  return {
    runtimePickerSaving: false,
    runtimePickerError: '',
    runtimePickerDraftProvider: '',
    runtimePickerDraftModel: '',

    toggleRuntimePicker() {
      this.chatModelOpen = !this.chatModelOpen;
      if (this.chatModelOpen) this.prepareRuntimePicker();
    },

    prepareRuntimePicker() {
      this.runtimePickerError = '';
      const backend = String(this.settingsForm?.ai_backend || 'ollama').toLowerCase();
      this.runtimePickerDraftProvider = String(
        this.settingsForm?.api_provider
        || this.runtimeStatus?.selected_api_provider?.provider_id
        || 'deepseek'
      ).trim() || 'deepseek';

      if (backend === 'ollama') {
        if (!this.ollamaModels.length) this.loadOllamaModels?.();
        return;
      }

      if (backend === 'cli') {
        this.runtimePickerDraftModel = String(
          this.settingsForm?.cli_runtime_model
          || this.runtimeStatus?.cli_model
          || ''
        ).trim();
        return;
      }

      this.runtimePickerDraftModel = String(
        this.providerValue?.(this.runtimePickerDraftProvider, 'model')
        || this.selectedApiProviderModel?.()
        || ''
      ).trim();
    },

    async applyOllamaChatModel(modelName) {
      const nextModel = String(modelName || '').trim();
      if (!nextModel || this.runtimePickerSaving) return;
      this.runtimePickerSaving = true;
      this.runtimePickerError = '';
      try {
        this.selectedChatModel = nextModel;
        this.settingsForm.ollama_model = nextModel;
        this.settingsForm.code_model = nextModel;
        await this.api('POST', '/api/settings', {
          ai_backend: 'ollama',
          ollama_model: nextModel,
          code_model: nextModel,
        });
        await this.loadRuntimeStatus?.();
        this.chatModelOpen = false;
      } catch (e) {
        this.runtimePickerError = e?.message || 'Unable to switch Ollama model';
        this.showToast?.(this.runtimePickerError);
      } finally {
        this.runtimePickerSaving = false;
      }
    },

    currentCliRuntimeModel() {
      return String(this.settingsForm?.cli_runtime_model || this.runtimeStatus?.cli_model || '').trim();
    },

    async applyCliRuntimeModel(modelId = '') {
      if (this.runtimePickerSaving) return;
      const nextModel = String(modelId || '').trim();
      this.runtimePickerSaving = true;
      this.runtimePickerError = '';
      try {
        this.settingsForm.ai_backend = 'cli';
        this.settingsForm.cli_runtime_model = nextModel;
        this.runtimePickerDraftModel = nextModel;
        await this.api('POST', '/api/settings', {
          ai_backend: 'cli',
          cli_runtime_model: nextModel,
        });
        await this.loadRuntimeStatus?.();
        this.chatModelOpen = false;
      } catch (e) {
        this.runtimePickerError = e?.message || 'Unable to switch CLI model';
        this.showToast?.(this.runtimePickerError);
      } finally {
        this.runtimePickerSaving = false;
      }
    },

    runtimePickerProviderCards() {
      return Array.isArray(this.runtimeStatus?.api_providers) ? this.runtimeStatus.api_providers : [];
    },

    runtimePickerSelectedProviderId() {
      return String(
        this.runtimePickerDraftProvider
        || this.settingsForm?.api_provider
        || this.runtimeStatus?.selected_api_provider?.provider_id
        || 'deepseek'
      ).trim() || 'deepseek';
    },

    runtimePickerApiModelPlaceholder() {
      const providerId = this.runtimePickerSelectedProviderId();
      const card = this.runtimePickerProviderCards().find(item => item.id === providerId) || null;
      return card?.model_placeholder || card?.default_model || 'Enter model';
    },

    async applyApiRuntimeProvider(providerId) {
      const nextProvider = String(providerId || '').trim();
      if (!nextProvider || this.runtimePickerSaving) return;
      this.runtimePickerSaving = true;
      this.runtimePickerError = '';
      try {
        this.settingsForm.ai_backend = 'api';
        this.settingsForm.api_provider = nextProvider;
        this.runtimePickerDraftProvider = nextProvider;
        await this.api('POST', '/api/settings', {
          ai_backend: 'api',
          api_provider: nextProvider,
        });
        await this.loadRuntimeStatus?.();
        const card = this.runtimePickerProviderCards().find(item => item.id === nextProvider) || null;
        this.runtimePickerDraftModel = String(
          this.providerValue?.(nextProvider, 'model')
          || card?.model
          || card?.default_model
          || ''
        ).trim();
      } catch (e) {
        this.runtimePickerError = e?.message || 'Unable to switch provider';
        this.showToast?.(this.runtimePickerError);
      } finally {
        this.runtimePickerSaving = false;
      }
    },

    async saveApiRuntimeModel() {
      const providerId = this.runtimePickerSelectedProviderId();
      if (!providerId || this.runtimePickerSaving) return;
      const field = this.providerModelField?.(providerId);
      if (!field) return;
      const nextModel = String(this.runtimePickerDraftModel || '').trim();
      this.runtimePickerSaving = true;
      this.runtimePickerError = '';
      try {
        this.settingsForm.ai_backend = 'api';
        this.settingsForm.api_provider = providerId;
        this.settingsForm[field] = nextModel;
        await this.api('POST', '/api/settings', {
          ai_backend: 'api',
          api_provider: providerId,
          [field]: nextModel,
        });
        await this.loadRuntimeStatus?.();
        this.chatModelOpen = false;
      } catch (e) {
        this.runtimePickerError = e?.message || 'Unable to save API model';
        this.showToast?.(this.runtimePickerError);
      } finally {
        this.runtimePickerSaving = false;
      }
    },
  };
}

window.axonRuntimeSelectorMixin = axonRuntimeSelectorMixin;
