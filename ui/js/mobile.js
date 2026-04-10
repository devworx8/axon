/* ══════════════════════════════════════════════════════════════
   Axon — Mobile / Analysis / SMART Tasks / GitHub / Integrations Module
   ══════════════════════════════════════════════════════════════ */
function axonMobileMixin() {
  const trimText = (value = '') => String(value || '').trim();
  const browserSpeechRecognition = () => window.webkitSpeechRecognition || window.SpeechRecognition;
  const isStandaloneVoiceShell = () => !!(
    window.matchMedia?.('(display-mode: standalone)')?.matches
    || window.navigator?.standalone
  );
  const voiceRecorderExtension = (mimeType = '') => {
    const value = String(mimeType || '').toLowerCase();
    if (value.includes('wav')) return 'wav';
    if (value.includes('ogg')) return 'ogg';
    if (value.includes('mp4') || value.includes('m4a')) return 'm4a';
    return 'webm';
  };
  const mobileVoiceShellClass = 'axon-mobile-voice-shell';
  const ensureMobileVoiceShellStyle = () => { if (typeof document === 'undefined' || document.getElementById?.('axon-mobile-voice-style') || !document.createElement) return; const style = document.createElement('style'); style.id = 'axon-mobile-voice-style'; style.textContent = `html.${mobileVoiceShellClass} nav[aria-label="Main navigation"],body.${mobileVoiceShellClass} nav[aria-label="Main navigation"]{display:none!important;}`; document.head?.appendChild?.(style); };
  const setMobileVoiceChrome = (active = false) => { if (typeof document === 'undefined') return; ensureMobileVoiceShellStyle(); document.documentElement?.classList?.toggle(mobileVoiceShellClass, !!active); document.body?.classList?.toggle(mobileVoiceShellClass, !!active); const nav = document.querySelector('nav[aria-label="Main navigation"]'); if (!nav) return; nav.hidden = !!active; nav.setAttribute?.('aria-hidden', active ? 'true' : 'false'); nav.style.display = active ? 'none' : ''; };
  return {
    syncMobileVoiceChrome() {
      const mobileShellOpen = !!(this.showVoiceOrb && (this.isMobile || window.innerWidth < 768));
      setMobileVoiceChrome(mobileShellOpen);
      requestAnimationFrame?.(() => setMobileVoiceChrome(!!(this.showVoiceOrb && (this.isMobile || window.innerWidth < 768))));
      if (this.showVoiceOrb) this.showMoreMenu = false;
    },
    openVoiceCommandCenter() {
      const resumeActive = !!(this.currentWorkspaceRunActive?.() || this.chatLoading || this.liveOperator?.active);
      if (this.voiceFileViewer?.open) this.closeVoiceFileViewer?.();
      this.showVoiceOrb = true;
      this.switchTab('chat');
      this.refreshVoiceCapability?.();
      this.ensureVoiceDefaultConversationMode?.();
      Promise.resolve()
        .then(() => this.loadVoiceStatus?.())
        .catch(() => {});
      this.ensureVoiceConversationState?.();
      this.initVoiceSurfaceDirector?.();
      if (this.chatInput && !this.voiceTranscript) {
        this.voiceTranscript = this.chatInput;
      }
      if (!resumeActive && window.axonVoiceBootSound) {
        window.axonVoiceBootSound.play();
      }
      this._scheduleBootGreeting?.();
      this.syncVoiceCommandCenterRuntime?.();
      this.syncVoiceSurfaceDirector?.({ force: true });
      this.syncMobileVoiceChrome();
      requestAnimationFrame?.(() => this.syncMobileVoiceChrome());
      // Auto-start listening on mobile/PWA (hands-free capture)
      this._scheduleVoiceAutoListen?.();
    },
    closeVoiceCommandCenter(stopCapture = true) {
      this._cleanupVoiceAutoCapture?.();
      this.showVoiceOrb = false;
      if (this.voiceFileViewer?.open) this.closeVoiceFileViewer?.();
      this.stopVoiceSurfaceDirector?.();
      this.syncMobileVoiceChrome();
      requestAnimationFrame?.(() => this.syncMobileVoiceChrome());
      this._cancelNarrationQueue?.();
      this.clearVoiceAwaitingReply?.();
      if (typeof this.stopSpeech === 'function') this.stopSpeech();
      this.closeVoiceConversationRuntime?.();
      if (stopCapture && this.voiceActive) {
        this.startVoice();
      }
    },
    refreshVoiceCapability() {
      const hasBrowserRecognition = !!browserSpeechRecognition();
      const hasAzureSdk = !!window.SpeechSDK;
      const hasRecorder = this.voiceCanRecordInBrowser?.() || false;
      const recorderReady = this.voiceRecorderBackendReady?.() || false;
      const azureSpeechReady = typeof this.azureSpeechConfigured === 'function' && this.azureSpeechConfigured();
      this.speechInputSupported = hasBrowserRecognition || (hasAzureSdk && azureSpeechReady) || (hasRecorder && recorderReady);
      this.speechOutputSupported = !!window.speechSynthesis || azureSpeechReady;
      this.speechSupported = this.speechInputSupported || this.speechOutputSupported;
      if (this.showVoiceOrb && this.voiceShouldDefaultToAgentMode?.()) {
        this.ensureVoiceDefaultConversationMode?.();
      }
    },
    voiceCanRecordInBrowser() {
      return !!(window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
    },
    voiceRecorderBackendReady() {
      return !!(
        this.voiceStatus?.transcription_ready
        || this.voiceStatus?.transcription_available
        || this.voiceStatus?.cloud_transcription_available
      );
    },
    voiceShouldUseRecordedCapture() {
      if (!this.voiceCanRecordInBrowser()) return false;
      if (!this.voiceRecorderBackendReady()) return false;
      return !!(this.isMobile || window.innerWidth < 768 || isStandaloneVoiceShell() || !browserSpeechRecognition());
    },
    async requestVoiceMicrophoneStream() {
      const isTrustedLocal = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
      if (!isTrustedLocal && !window.isSecureContext) {
        this.showToast('Voice input needs HTTPS or localhost');
        return null;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.showToast('Microphone capture is not available in this browser');
        return null;
      }
      try {
        return await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        const name = String(e?.name || '').toLowerCase();
        if (name.includes('notallowed') || name.includes('permission')) {
          this.showToast('Microphone blocked — open Android Settings → Apps → Chrome → Permissions → Microphone → Allow, then retry');
        } else {
          this.showToast('Could not access the microphone');
        }
        return null;
      }
    },
    voiceRecorderMimeType() {
      if (!window.MediaRecorder?.isTypeSupported) return '';
      const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
      return candidates.find(candidate => window.MediaRecorder.isTypeSupported(candidate)) || '';
    },
    async transcribeRecordedVoiceCapture(chunks = [], mimeType = 'audio/webm') {
      const audioChunks = Array.isArray(chunks) ? chunks.filter(Boolean) : [];
      if (!audioChunks.length) {
        this.showToast('No speech was captured');
        return '';
      }
      try {
        await this.loadVoiceStatus?.();
        if (!this.voiceRecorderBackendReady()) {
          throw new Error(this.voiceStatus?.detail || 'No transcription backend is available');
        }
        const blob = new Blob(audioChunks, { type: mimeType || 'audio/webm' });
        const form = new FormData();
        form.append('file', blob, `axon-voice.${voiceRecorderExtension(mimeType)}`);
        const url = `/api/voice/transcribe?language=${encodeURIComponent(this.speechLocale?.() || 'en-US')}`;
        const response = await fetch(url, {
          method: 'POST',
          headers: this.authHeaders ? this.authHeaders() : {},
          body: form,
        });
        if (response.status === 401) {
          this.handleAuthRequired?.();
          throw new Error('Session expired');
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload?.detail || 'Voice transcription failed');
        }
        const text = trimText(payload?.text || '');
        if (!text) {
          this.showToast('No speech was detected');
          return '';
        }
        const consumed = !!this.handleVoiceCaptureTranscript?.(text, { final: true, source: 'recorded' });
        if (!consumed) this.syncVoiceTranscript?.(text);
        return text;
      } catch (e) {
        this.showToast(e?.message || 'Voice transcription failed');
        return '';
      }
    },
    async startRecordedVoiceCapture(stream) {
      const captureStream = stream || await this.requestVoiceMicrophoneStream?.();
      if (!captureStream) return false;
      if (!window.MediaRecorder) {
        captureStream.getTracks().forEach(track => track.stop());
        this.showToast('Audio recording is not available in this browser');
        return false;
      }
      const mimeType = this.voiceRecorderMimeType?.() || '';
      const chunks = [];
      const recorder = mimeType ? new window.MediaRecorder(captureStream, { mimeType }) : new window.MediaRecorder(captureStream);
      this._voiceCaptureStream = captureStream;
      this._voiceRecorder = recorder;
      this._voiceRecorderChunks = chunks;
      this._voiceRecorderMimeType = mimeType || recorder.mimeType || 'audio/webm';
      this._voiceRecorderPromise = new Promise((resolve) => {
        this._voiceRecorderResolve = resolve;
      });
      let finished = false;
      const finish = async (transcribe = true) => {
        if (finished) return '';
        finished = true;
        const transcript = transcribe
          ? await this.transcribeRecordedVoiceCapture?.(chunks, this._voiceRecorderMimeType || 'audio/webm')
          : '';
        captureStream.getTracks().forEach(track => track.stop());
        this.voiceActive = false;
        this._voiceCaptureStream = null;
        this._voiceRecorder = null;
        this._voiceRecorderChunks = [];
        this._voiceRecorderMimeType = '';
        const resolve = this._voiceRecorderResolve;
        this._voiceRecorderResolve = null;
        this._voiceRecorderPromise = null;
        resolve?.(transcript);
        this.handleVoiceCaptureLifecycle?.('end', { reason: transcribe ? 'result' : 'cancelled' });
      };
      recorder.ondataavailable = (event) => {
        if (event?.data?.size) chunks.push(event.data);
      };
      recorder.onerror = async (event) => {
        this.showToast(trimText(event?.error?.message || event?.message || 'Voice recording failed'));
        this.handleVoiceCaptureLifecycle?.('error', { code: 'recording-error', event });
        await finish(false);
      };
      recorder.onstop = async () => {
        await finish(true);
      };
      this.voiceSessionStartedAt = new Date().toISOString();
      this.voiceActive = true;
      try {
        recorder.start();
        this._initVoiceVAD?.(captureStream);
      } catch (e) {
        captureStream.getTracks().forEach(track => track.stop());
        this.voiceActive = false;
        this._voiceCaptureStream = null;
        this._voiceRecorder = null;
        this._voiceRecorderChunks = [];
        this._voiceRecorderMimeType = '';
        this._voiceRecorderResolve?.('');
        this._voiceRecorderResolve = null;
        this._voiceRecorderPromise = null;
        this.showToast(e?.message || 'Voice recording could not start');
        return false;
      }
      return true;
    },
    async stopRecordedVoiceCapture() {
      this._destroyVoiceVAD?.();
      const recorder = this._voiceRecorder;
      const pending = this._voiceRecorderPromise;
      if (!recorder) return '';
      try {
        recorder.stop();
      } catch (e) {
        this.showToast(e?.message || 'Voice capture could not stop cleanly');
        return '';
      }
      return pending || '';
    },
    voiceCenterStatusDetail() {
      const conversationDetail = this.voiceConversationStatusDetail?.();
      if (conversationDetail) return conversationDetail;
      if (this._voiceRecorder) {
        return 'Axon is recording through the browser mic. Tap again when you are ready to transcribe and run it.';
      }
      if (this.voiceActive) return 'Axon is capturing your voice and updating the command live.';
      if (this.chatLoading) return this.liveOperator?.detail || 'Axon is working through the latest command.';
      if (this.voiceTranscript) return 'Review the transcript, then send it or keep dictating.';
      return this.voiceOutputAvailable?.() ? 'Voice replies can be spoken automatically when Auto-speak is on.' : 'Configure browser or Azure speech to enable spoken replies.';
    },
    async startVoice() {
      if (this.voiceActive && this._voiceRecorder) {
        return this.stopRecordedVoiceCapture();
      }
      if (this.voiceActive && this._speechRecognizer) {
        try {
          if (typeof this._speechRecognizer.stop === 'function') this._speechRecognizer.stop();
          if (typeof this._speechRecognizer.close === 'function') this._speechRecognizer.close();
        } catch (_) {}
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.showToast('Voice capture stopped');
        return '';
      }
      try {
        await this.loadVoiceStatus?.();
      } catch (_) {}
      const SpeechRec = browserSpeechRecognition();
      if (this.voiceShouldUseRecordedCapture()) {
        const started = await this.startRecordedVoiceCapture();
        if (!started) {
          this.showToast('Could not start voice recording — check microphone permission');
        }
        return '';
      }
      const stream = await this.requestVoiceMicrophoneStream?.();
      if (!stream) {
        return '';
      }
      stream.getTracks().forEach(track => track.stop());
      if (!SpeechRec && window.SpeechSDK && this.azureSpeechConfigured?.()) {
        await this.startAzureVoiceRecognition();
        return '';
      }
      if (!SpeechRec) {
        if (this.voiceCanRecordInBrowser() && this.voiceRecorderBackendReady()) {
          await this.startRecordedVoiceCapture();
          return '';
        }
        this.showToast(this.voiceStatus?.detail || 'This browser does not expose live speech recognition here');
        return '';
      }

      const recog = new SpeechRec();
      this._speechRecognizer = recog;
      recog.lang = this.speechLocale();
      recog.interimResults = true;
      recog.maxAlternatives = 1;
      if ('continuous' in recog) recog.continuous = false;
      this.voiceSessionStartedAt = new Date().toISOString();
      this.voiceActive = true;
      recog.onresult = (e) => {
        let finalTranscript = '';
        let interimTranscript = '';
        for (let idx = e.resultIndex || 0; idx < (e.results?.length || 0); idx += 1) {
          const result = e.results[idx];
          const transcript = result?.[0]?.transcript || '';
          if (result?.isFinal) finalTranscript += `${transcript} `;
          else interimTranscript += `${transcript} `;
        }
        const combined = `${finalTranscript}${interimTranscript}`.trim();
        if (!combined) {
          const handledNoSpeech = this.handleVoiceCaptureLifecycle?.('error', { code: 'no-speech' });
          if (!handledNoSpeech) this.showToast('No speech was detected');
        } else {
          const finalOnly = !!(finalTranscript.trim() && !interimTranscript.trim());
          const consumed = finalOnly
            ? !!this.handleVoiceCaptureTranscript?.(combined, { final: true, source: 'browser' })
            : false;
          if (!consumed) this.syncVoiceTranscript(combined);
        }
        if (finalTranscript.trim() && !interimTranscript.trim()) {
          this.voiceActive = false;
          this._speechRecognizer = null;
          this.handleVoiceCaptureLifecycle?.('end', { reason: 'result' });
        }
      };
      recog.onerror = (event) => {
        this.voiceActive = false;
        this._speechRecognizer = null;
        const code = String(event?.error || '').toLowerCase();
        const handled = this.handleVoiceCaptureLifecycle?.('error', { code, event });
        if (handled && ['no-speech', 'aborted'].includes(code)) return;
        if (code === 'not-allowed' || code === 'service-not-allowed') {
          this.showToast('Microphone permission was denied');
        } else if (code === 'network') {
          this.showToast('Speech recognition network error');
        } else if (code === 'no-speech') {
          this.showToast('No speech detected');
        } else if (code === 'audio-capture') {
          this.showToast('No microphone was found');
        } else {
          this.showToast(code ? `Voice input failed: ${code}` : 'Voice input failed');
        }
      };
      recog.onend = () => {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.handleVoiceCaptureLifecycle?.('end', { reason: 'end' });
      };
      try {
        recog.start();
      } catch (e) {
        this.voiceActive = false;
        this._speechRecognizer = null;
        this.showToast(`Voice input could not start: ${e.message || e}`);
      }
      return '';
    },
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
