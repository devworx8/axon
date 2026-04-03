/* ═══════════════════════════════════════════════════
   Axon — Attention Inbox module
   ═══════════════════════════════════════════════════ */

function axonAttentionMixin() {
  return {
    attentionInbox: { counts: { now: 0, waiting_on_me: 0, watch: 0 }, now: [], waiting_on_me: [], watch: [] },
    attentionLoading: false,
    attentionError: '',
    attentionUpdatedAt: '',

    async loadAttentionInbox(workspaceId = '', limit = 18) {
      if (this.attentionLoading) return;
      this.attentionLoading = true;
      try {
        const params = new URLSearchParams();
        params.set('limit', String(limit || 18));
        const targetWorkspace = String(workspaceId || '').trim();
        if (targetWorkspace) params.set('workspace_id', targetWorkspace);
        const data = await this.api('GET', `/api/attention/inbox?${params.toString()}`);
        this.attentionInbox = {
          counts: {
            now: Number(data?.counts?.now || 0),
            waiting_on_me: Number(data?.counts?.waiting_on_me || 0),
            watch: Number(data?.counts?.watch || 0),
          },
          now: Array.isArray(data?.now) ? data.now : [],
          waiting_on_me: Array.isArray(data?.waiting_on_me) ? data.waiting_on_me : [],
          watch: Array.isArray(data?.watch) ? data.watch : [],
        };
        this.attentionUpdatedAt = new Date().toISOString();
        this.attentionError = '';
      } catch (e) {
        console.error('[attention] Failed to load inbox:', e);
        this.attentionError = e?.message || 'Failed to load attention inbox';
      } finally {
        this.attentionLoading = false;
      }
    },

    attentionBucketLabel(bucket) {
      if (bucket === 'waiting_on_me') return 'Waiting on me';
      if (bucket === 'watch') return 'Watch';
      return 'Now';
    },

    attentionBucketItems(bucket) {
      const items = this.attentionInbox?.[bucket];
      return Array.isArray(items) ? items.slice(0, 4) : [];
    },

    attentionBucketCount(bucket) {
      return Number(this.attentionInbox?.counts?.[bucket] || 0);
    },

    attentionBucketTone(bucket) {
      if (bucket === 'now') return 'border-rose-500/20 bg-rose-500/8 text-rose-200';
      if (bucket === 'waiting_on_me') return 'border-amber-500/20 bg-amber-500/8 text-amber-200';
      return 'border-cyan-500/20 bg-cyan-500/8 text-cyan-200';
    },

    attentionSourceTone(source = '') {
      const key = String(source || '').trim().toLowerCase();
      if (key === 'github') return 'border-slate-600 bg-slate-950/80 text-slate-200';
      if (key === 'vercel') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (key === 'sentry') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      if (key === 'browser') return 'border-sky-500/20 bg-sky-500/10 text-sky-200';
      if (key === 'runtime') return 'border-violet-500/20 bg-violet-500/10 text-violet-200';
      return 'border-slate-700 bg-slate-950/70 text-slate-300';
    },

    attentionSeverityTone(item = {}) {
      const severity = String(item?.severity || '').trim().toLowerCase();
      if (severity === 'critical' || severity === 'fatal') return 'text-rose-300';
      if (severity === 'high') return 'text-amber-300';
      return 'text-slate-400';
    },

    attentionPrimaryActionLabel(item = {}) {
      if (String(item?.link_url || '').trim()) return 'Open link';
      if (Number(item?.workspace_id || 0) > 0) return 'Open workspace';
      return 'Inspect';
    },

    openAttentionItem(item = {}) {
      const linkUrl = String(item?.link_url || '').trim();
      if (linkUrl) {
        window.open(linkUrl, '_blank', 'noopener');
        return;
      }
      const workspaceId = String(item?.workspace_id || '').trim();
      if (workspaceId) {
        this.chatProjectId = workspaceId;
        this.updateChatProject?.();
        this.switchTab?.('chat');
        return;
      }
      this.switchTab?.('devops');
    },

    async acknowledgeAttentionItem(itemOrId) {
      const attentionId = Number(typeof itemOrId === 'object' ? itemOrId?.id : itemOrId);
      if (!attentionId) return;
      try {
        await this.api('POST', `/api/attention/items/${attentionId}/ack`, {});
        this.showToast?.('Attention item acknowledged');
        await this.loadAttentionInbox();
      } catch (e) {
        console.error('[attention] Failed to acknowledge item:', e);
        this.showToast?.('Failed to acknowledge attention item');
      }
    },

    async resolveAttentionItem(itemOrId) {
      const attentionId = Number(typeof itemOrId === 'object' ? itemOrId?.id : itemOrId);
      if (!attentionId) return;
      try {
        await this.api('POST', `/api/attention/items/${attentionId}/resolve`, {});
        this.showToast?.('Attention item resolved');
        await this.loadAttentionInbox();
      } catch (e) {
        console.error('[attention] Failed to resolve item:', e);
        this.showToast?.('Failed to resolve attention item');
      }
    },
  };
}

window.axonAttentionMixin = axonAttentionMixin;
