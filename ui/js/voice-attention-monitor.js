/* ══════════════════════════════════════════════════════════════
   Axon — Voice Attention Monitor
   ══════════════════════════════════════════════════════════════ */

function axonVoiceAttentionMonitorMixin() {
  const ENABLED_VALUES = new Set(['1', 'true', 'yes', 'on']);
  const LIVE_ALERT_STATUSES = new Set(['approval_required', 'error']);

  const topItemLabel = (item = {}) => {
    const summary = String(item?.summary || item?.title || item?.detail || '').trim();
    if (summary) return summary;
    return String(item?.item_type || item?.status || 'attention item').replace(/_/g, ' ').trim();
  };

  const attentionFingerprint = (summary = {}) => JSON.stringify({
    counts: summary?.counts || {},
    top_now: (summary?.top_now || []).slice(0, 2).map(item => [item?.id, item?.status, item?.severity, item?.summary]),
    top_waiting_on_me: (summary?.top_waiting_on_me || []).slice(0, 2).map(item => [item?.id, item?.status, item?.severity, item?.summary]),
  });

  return {
    voiceAttentionMonitor: {
      started: false,
      busy: false,
      timer: null,
      intervalMs: 30000,
      lastSummaryFingerprint: '',
      lastLiveFingerprint: '',
      lastAnnouncedAt: '',
    },

    voiceAttentionEnabled() {
      const raw = this.settingsForm?.voice_attention_enabled;
      if (typeof raw === 'boolean') return raw;
      if (raw == null || raw === '') return true;
      return ENABLED_VALUES.has(String(raw).trim().toLowerCase());
    },

    voiceAttentionAutowakeEnabled() {
      const raw = this.settingsForm?.voice_attention_autowake;
      if (typeof raw === 'boolean') return raw;
      if (raw == null || raw === '') return true;
      return ENABLED_VALUES.has(String(raw).trim().toLowerCase());
    },

    voiceAttentionMonitoringActive() {
      const mode = String(this.activePrimaryConversationMode?.() || '').trim().toLowerCase();
      if (mode === 'auto') return true;
      const operatorMode = String(this.liveOperator?.mode || '').trim().toLowerCase();
      return operatorMode === 'auto';
    },

    ensureVoiceAttentionMonitor() {
      if (this.voiceAttentionMonitor?.started) return;
      this.voiceAttentionMonitor.started = true;
      const tick = async () => {
        await this.pollVoiceAttentionSummary?.();
        const intervalMs = Math.max(12000, Number(this.voiceAttentionMonitor?.intervalMs || 30000));
        this.voiceAttentionMonitor.timer = window.setTimeout(tick, intervalMs);
      };
      this.voiceAttentionMonitor.timer = window.setTimeout(tick, 2500);
    },

    async pollVoiceAttentionSummary(force = false) {
      if (!force && !this.voiceAttentionMonitoringActive?.()) return null;
      if (!this.voiceAttentionEnabled?.() || !this.speechOutputSupported) return null;
      if (this.voiceAttentionMonitor?.busy) return null;
      this.voiceAttentionMonitor.busy = true;
      try {
        const params = new URLSearchParams();
        params.set('limit', '6');
        const workspaceId = String(this.chatProjectId || '').trim();
        if (workspaceId) params.set('workspace_id', workspaceId);
        const summary = await this.api('GET', `/api/attention/summary?${params.toString()}`);
        this.maybeAnnounceAttentionSummary?.(summary, { force });
        return summary;
      } catch (_) {
        return null;
      } finally {
        this.voiceAttentionMonitor.busy = false;
      }
    },

    maybeAnnounceAttentionSummary(summary = {}, options = {}) {
      if (!this.voiceAttentionEnabled?.() || !this.speechOutputSupported) return false;
      if (!options?.force && !this.voiceAttentionMonitoringActive?.()) return false;
      const counts = summary?.counts || {};
      const urgentCount = Number(counts.now || 0);
      const waitingCount = Number(counts.waiting_on_me || 0);
      if (urgentCount <= 0 && waitingCount <= 0) return false;
      const fingerprint = attentionFingerprint(summary);
      if (!options?.force && fingerprint && fingerprint === this.voiceAttentionMonitor?.lastSummaryFingerprint) {
        return false;
      }
      this.voiceAttentionMonitor.lastSummaryFingerprint = fingerprint;
      const topWaiting = Array.isArray(summary?.top_waiting_on_me) ? summary.top_waiting_on_me[0] : null;
      const topNow = Array.isArray(summary?.top_now) ? summary.top_now[0] : null;
      const workspace = this.workspaceTabLabel?.()
        || this.chatProject?.name
        || (this.chatProjectId ? `workspace ${this.chatProjectId}` : 'your workspaces');
      let message = '';
      if (topWaiting) {
        message = `Axon alert. ${workspace} is waiting on you. ${topItemLabel(topWaiting)}.`;
      } else if (topNow) {
        message = `Axon alert. ${workspace} has a fresh issue. ${topItemLabel(topNow)}.`;
      }
      if (!message) return false;
      this.announceVoiceAttention?.(message, { source: 'attention_summary' });
      return true;
    },

    syncVoiceAttentionFromLiveFeed(payload = {}) {
      if (!this.voiceAttentionEnabled?.() || !this.speechOutputSupported) return false;
      if (!this.voiceAttentionMonitoringActive?.()) return false;
      const operator = payload?.operator || {};
      const workspaceId = String(this.chatProjectId || '').trim();
      let alertKey = '';
      let message = '';

      const operatorPhase = String(operator?.phase || '').trim().toLowerCase();
      const operatorWorkspaceId = String(operator?.workspace_id || '').trim();
      if (operator?.active && operatorPhase === 'recover' && (!workspaceId || workspaceId === operatorWorkspaceId)) {
        alertKey = JSON.stringify(['operator', operatorWorkspaceId, operatorPhase, operator?.title, operator?.detail]);
        message = `Axon alert. ${String(operator?.title || 'Autonomous run needs attention').trim()}. ${String(operator?.detail || '').trim()}`.trim();
      }

      if (!message && Array.isArray(payload?.auto_sessions)) {
        const current = payload.auto_sessions.find(session => {
          const status = String(session?.status || '').trim().toLowerCase();
          if (!LIVE_ALERT_STATUSES.has(status)) return false;
          if (!workspaceId) return true;
          return String(session?.workspace_id || '') === workspaceId;
        });
        if (current) {
          const status = String(current?.status || '').trim().toLowerCase();
          alertKey = JSON.stringify(['auto', current?.session_id, status, current?.detail, current?.last_error]);
          if (status === 'approval_required') {
            message = `Axon alert. ${String(current?.title || 'Autonomous run').trim()} is paused for approval. ${String(current?.detail || '').trim()}`.trim();
          } else if (status === 'error') {
            message = `Axon alert. ${String(current?.title || 'Autonomous run').trim()} hit an error. ${String(current?.last_error || current?.detail || '').trim()}`.trim();
          }
        }
      }

      if (!message || !alertKey) return false;
      if (alertKey === this.voiceAttentionMonitor?.lastLiveFingerprint) return false;
      this.voiceAttentionMonitor.lastLiveFingerprint = alertKey;
      this.announceVoiceAttention?.(message, { source: 'live_feed' });
      return true;
    },

    announceVoiceAttention(message = '', options = {}) {
      const content = String(message || '').replace(/\s+/g, ' ').trim();
      if (!content) return false;
      this.voiceAttentionMonitor.lastAnnouncedAt = new Date().toISOString();
      if (this.voiceAttentionAutowakeEnabled?.()) {
        this.openVoiceCommandCenter?.();
      }
      this.showStickyNotification?.({
        title: 'Axon alert',
        body: content,
        type: 'warning',
        icon: 'A',
        duration: 0,
        sound: true,
        action: { label: 'Open console', tab: 'chat' },
      });
      try {
        this.speakMessage?.(content);
      } catch (_) {}
      return true;
    },
  };
}

window.axonVoiceAttentionMonitorMixin = axonVoiceAttentionMonitorMixin;
