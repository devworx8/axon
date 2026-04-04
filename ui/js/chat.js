/* ══════════════════════════════════════════════════════════════
   Axon — Chat Module
   ══════════════════════════════════════════════════════════════ */

function axonChatMixin() {
  return {

    /* ── Composer helpers ─────────────────────────────────────── */

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

    scrollChat() {
      this.$nextTick(() => {
        const el = document.getElementById('chat-messages');
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    /* ── Mode resolution ──────────────────────────────────────── */

    resolveChatMode(msg) {
      const preferred = this.composerPreferredMode(msg);
      if (preferred) return preferred;
      return this.agentMode || this.shouldAutoUseAgent(msg) ? 'agent' : 'chat';
    },

    toggleAgentMode(force = null) {
      this.agentMode = typeof force === 'boolean' ? force : !this.agentMode;
      if (this.agentMode && this.usesOllamaBackend() && this.ollamaModels.length === 0) {
        this.loadOllamaModels();
      }
    },

    setAgentStage(phase) {
      if (this.agentLifecycle.includes(phase)) this.agentProgressState = phase;
    },

    /* ── Business mode ────────────────────────────────────────── */

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

    /* ── Live operator ────────────────────────────────────────── */

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

    ensureAssistantMessageBlocks(message) {
      if (!message) return;
      if (!Array.isArray(message.thinkingBlocks)) message.thinkingBlocks = [];
      if (!Array.isArray(message.workingBlocks)) message.workingBlocks = [];
      if (!message.providerIdentity) message.providerIdentity = this.assistantProviderIdentity();
    },

    appendThinkingBlock(message, chunk) {
      const text = String(chunk || '').trim();
      if (!text) return;
      this.ensureAssistantMessageBlocks(message);
      const last = message.thinkingBlocks[message.thinkingBlocks.length - 1];
      if (last && last.status === 'active') {
        last.content = `${last.content}\n\n${text}`.trim();
        last.updatedAt = new Date().toISOString();
        return;
      }
      message.thinkingBlocks.push({
        id: `think-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        title: 'Thinking',
        content: text,
        status: 'active',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
    },

    finalizeThinkingBlocks(message) {
      this.ensureAssistantMessageBlocks(message);
      message.thinkingBlocks.forEach(block => {
        if (block.status === 'active') block.status = 'done';
      });
    },

    appendWorkingBlock(message, event) {
      this.ensureAssistantMessageBlocks(message);
      message.workingBlocks.push({
        id: `work-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: event.name || '',
        title: `Working · ${this.prettyToolName(event.name)}`,
        args: event.args || {},
        result: '',
        status: 'running',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
    },

    resolveWorkingBlock(message, event) {
      this.ensureAssistantMessageBlocks(message);
      const match = [...message.workingBlocks].reverse().find(block => block.name === event.name && block.status === 'running');
      if (match) {
        match.status = 'done';
        match.result = String(event.result || '').trim();
        match.updatedAt = new Date().toISOString();
        return;
      }
      message.workingBlocks.push({
        id: `work-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: event.name || '',
        title: `Working · ${this.prettyToolName(event.name)}`,
        args: {},
        result: String(event.result || '').trim(),
        status: 'done',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      });
    },

    finalizeWorkingBlocks(message) {
      this.ensureAssistantMessageBlocks(message);
      message.workingBlocks.forEach(block => {
        if (block.status === 'running') {
          block.status = 'done';
          block.updatedAt = new Date().toISOString();
        }
      });
    },

    /* ── Streaming ────────────────────────────────────────────── */

    createAssistantPlaceholder(respId, mode, retryResources = []) {
      const providerIdentity = this.assistantProviderIdentity();
      return {
        id: respId,
        role: 'assistant',
        content: '',
        streaming: true,
        created_at: new Date().toISOString(),
        mode,
        modelLabel: providerIdentity.modelLabel || this.assistantRuntimeLabel(),
        providerIdentity,
        thinkingBlocks: [],
        workingBlocks: [],
        agentEvents: mode === 'agent' ? [] : undefined,
        retryResources,
      };
    },

    stopGeneration() {
      if (this._chatAbortController) {
        this._chatAbortController.abort();
        this._chatAbortController = null;
      }
      // Mark all streaming messages as done
      this.chatMessages.forEach(m => {
        if (m.streaming) m.streaming = false;
      });
      this.chatLoading = false;
      this.clearLiveOperator(400);
      this.showToast('Generation stopped');
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

      this._chatAbortController = new AbortController();
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: this.authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(payload),
        signal: this._chatAbortController.signal,
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
            this.ensureAssistantMessageBlocks(this.chatMessages[idx]);

            if (mode === 'agent') {
              if (data.type === 'thinking') {
                this.setAgentStage('plan');
                this.appendThinkingBlock(this.chatMessages[idx], data.chunk);
                this.updateLiveOperator(mode, { type: 'text' });
                this.scrollChat();
              } else if (data.type === 'text') {
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                if (this.chatMessages[idx].agentEvents?.length) this.setAgentStage('verify');
                this.chatMessages[idx].content += data.chunk;
                this.updateLiveOperator(mode, data);
                this.scrollChat();
              } else if (data.type === 'tool_call' || data.type === 'tool_result') {
                this.setAgentStage(data.type === 'tool_call' ? 'execute' : 'verify');
                this.chatMessages[idx].agentEvents.push(data);
                if (data.type === 'tool_call') {
                  this.finalizeThinkingBlocks(this.chatMessages[idx]);
                  this.appendWorkingBlock(this.chatMessages[idx], data);
                } else {
                  this.resolveWorkingBlock(this.chatMessages[idx], data);
                }
                this.updateLiveOperator(mode, data);
                this.scrollChat();
              } else if (data.type === 'done') {
                this.setAgentStage('verify');
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                this.finalizeWorkingBlocks(this.chatMessages[idx]);
                this.chatMessages[idx].streaming = false;
                // Auto-speak response if voice mode is active
                if (typeof this.autoSpeakResponse === 'function') {
                  this.autoSpeakResponse(this.chatMessages[idx].content);
                }
                this.updateLiveOperator(mode, data);
              } else if (data.type === 'error') {
                this.setAgentStage('recover');
                this.finalizeThinkingBlocks(this.chatMessages[idx]);
                this.finalizeWorkingBlocks(this.chatMessages[idx]);
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
                // Auto-speak response if voice mode is active
                if (typeof this.autoSpeakResponse === 'function') {
                  this.autoSpeakResponse(this.chatMessages[idx].content);
                }
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

      this._chatAbortController = null;
      const idx = this.chatMessages.findIndex(m => m.id === respId);
      if (idx >= 0) {
        this.finalizeThinkingBlocks(this.chatMessages[idx]);
        this.finalizeWorkingBlocks(this.chatMessages[idx]);
        this.chatMessages[idx].streaming = false;
        this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
      }
      this.clearLiveOperator(this.liveOperator.phase === 'recover' ? 4200 : 1400);
    },

    /* ── Chat CRUD ────────────────────────────────────────────── */

    async loadChatHistory() {
      try {
        const pid = this.chatProjectId ? `?project_id=${this.chatProjectId}&limit=40` : '?limit=40';
        const rows = await this.api('GET', `/api/chat/history${pid}`);
        this.chatMessages = rows.map(r => {
          const parsed = this.parseStoredChatMessage(r.content);
          return {
            id: r.created_at + r.role,
            role: r.role,
            content: parsed.content,
            created_at: r.created_at,
            mode: 'chat',
            resources: parsed.resources,
          };
        });
        this.$nextTick(() => this.scrollChat());
      } catch(e) {
        this.chatMessages = [];
      }
    },

    async sendChat() {
      if (this.businessMode && !this.chatInput?.trim()) {
        this.chatInput = this.businessComposerPrompt(this.businessView || 'invoice');
      }
      if (this.businessMode) {
        this.agentMode = false;
      }
      const msg = this.chatInput.trim();
      if (!msg || this.chatLoading) return;
      const mode = this.resolveChatMode(msg);
      const researchPack = this.currentResearchPack();
      const packResources = researchPack?.resources || [];
      const attachedResources = this.mergeUniqueResources([...packResources, ...this.selectedResources]);
      const attachedResourceIds = attachedResources.map(resource => Number(resource.id)).filter(Boolean);
      if (mode === 'agent' && !this.usesOllamaBackend()) {
        this.showToast('Agent mode requires the Ollama backend.');
        return;
      }
      this.setAgentStage(mode === 'agent' ? 'observe' : 'observe');

      this.chatInput = '';
      if (!this.composerOptions.pin_context) {
        this.selectedResources = [];
      }
      this.showResourcePicker = false;
      this.showComposerMenu = false;
      this.resetChatComposerHeight();
      this.chatMessages.push({
        id: Date.now(),
        role: 'user',
        content: msg,
        created_at: new Date().toISOString(),
        mode,
        resources: attachedResources,
      });
      this.chatLoading = true;
      this.beginLiveOperator(mode, msg);
      this.scrollChat();

      const respId = Date.now() + 1;
      this.chatMessages.push(this.createAssistantPlaceholder(respId, mode, attachedResourceIds));
      this.scrollChat();
      try {
        await this.streamChatMessage(msg, mode, respId, attachedResourceIds);
      } catch(e) {
        if (e.name === 'AbortError') {
          // User clicked stop — not an error
          this.chatLoading = false;
          this.scrollChat();
          return;
        }
        const idx = this.chatMessages.findIndex(m => m.id === respId);
        if (idx >= 0) {
          const isFetch = e.message === 'Failed to fetch' || e.message.includes('NetworkError');
          this.chatMessages[idx].content = `⚠️ ${mode === 'agent' ? 'Agent error: ' : ''}${isFetch ? 'Connection lost.' : e.message}`;
          this.chatMessages[idx].streaming = false;
          this.chatMessages[idx].error = true;
          this.chatMessages[idx].retryMsg = msg;
          this.chatMessages[idx].mode = mode;
          if (isFetch) this.serverConnected = false;
          this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
        }
        if (mode === 'agent') this.setAgentStage('recover');
        this.updateLiveOperator(mode, { type: 'error', message: e.message === 'Failed to fetch' || e.message.includes('NetworkError') ? 'Connection lost.' : e.message });
        this.clearLiveOperator(4200);
      }

      this.chatLoading = false;
      this.scrollChat();
    },

    async retryChat(errorMsg) {
      const msg = errorMsg.retryMsg;
      if (!msg) return;
      const mode = errorMsg.mode || this.resolveChatMode(msg);
      const researchPack = this.currentResearchPack();
      const resourceIds = (errorMsg.retryResources && errorMsg.retryResources.length)
        ? errorMsg.retryResources
        : (researchPack?.resources || []).map(resource => Number(resource.id)).filter(Boolean);
      this.chatMessages = this.chatMessages.filter(m => m.id !== errorMsg.id);
      this.chatLoading = true;
      this.beginLiveOperator(mode, msg);
      this.scrollChat();
      const respId = Date.now() + 1;
      this.chatMessages.push(this.createAssistantPlaceholder(respId, mode, resourceIds));
      try {
        await this.streamChatMessage(msg, mode, respId, resourceIds);
      } catch(e) {
        if (e.name === 'AbortError') {
          this.chatLoading = false;
          this.scrollChat();
          return;
        }
        const idx = this.chatMessages.findIndex(m => m.id === respId);
        const isFetch = e.message === 'Failed to fetch' || e.message.includes('NetworkError');
        if (isFetch) this.serverConnected = false;
        if (idx >= 0) {
          this.chatMessages[idx].content = isFetch
            ? '⚠️ Connection lost — check your network.'
            : `⚠️ ${mode === 'agent' ? 'Agent error: ' : 'Error: '}${e.message}`;
          this.chatMessages[idx].streaming = false;
          this.chatMessages[idx].error = true;
          this.chatMessages[idx].retryMsg = msg;
          this.chatMessages[idx].mode = mode;
          this.rememberOperatorOutcome(mode, this.chatMessages[idx]);
        }
        if (mode === 'agent') this.setAgentStage('recover');
        this.updateLiveOperator(mode, { type: 'error', message: isFetch ? 'Connection lost.' : e.message });
        this.clearLiveOperator(4200);
      }
      this.chatLoading = false;
      this.scrollChat();
    },

    /* ── Canvas ───────────────────────────────────────────────── */

    openCanvas(message) {
      if (!message) return;
      const baseTitle = message.role === 'user' ? 'Your note' : 'Axon response';
      const derivedTitle = this.documentTitleFromMarkdown(message.content) || baseTitle;
      const runtimeBits = [
        message.mode === 'agent' ? '#NEXT-GEN' : 'Console',
        message.modelLabel || this.assistantRuntimeLabel() || '',
        message.created_at ? `Updated ${this.formatTime(message.created_at)}` : '',
      ].filter(Boolean);
      this.canvasModal = {
        open: true,
        title: derivedTitle,
        content: message.content || '',
        meta: runtimeBits.join(' · '),
        messageId: message.id || null,
      };
      document.body.classList.add('overflow-hidden');
    },

    /* ── Rendering helpers ────────────────────────────────────── */

    renderMd(text) {
      if (!text || typeof marked === 'undefined') return text || '';
      if (!this._markdownConfigured) {
        marked.setOptions({
          gfm: true,
          breaks: true,
          headerIds: false,
          mangle: false,
        });
        this._markdownConfigured = true;
      }
      const html = marked.parse(String(text || ''));
      return this.sanitizeRenderedHtml(html);
    },

    formatTime(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      const now = new Date();
      const diff = now - d;
      if (diff < 60000) return 'just now';
      if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
      if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
      return d.toLocaleDateString();
    },

  };
}

window.axonChatMixin = axonChatMixin;
