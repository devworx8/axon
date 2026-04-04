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

    attentionBucketItems(bucket, limit = 4, offset = 0) {
      const items = this.attentionInbox?.[bucket];
      const rows = Array.isArray(items) ? items : [];
      const start = Math.max(0, Number(offset || 0));
      const size = Number(limit || 0);
      return size > 0 ? rows.slice(start, start + size) : rows.slice(start);
    },

    attentionBucketCount(bucket) {
      return Number(this.attentionInbox?.counts?.[bucket] || 0);
    },

    attentionBucketLeadItem(bucket) {
      return this.attentionBucketItems(bucket, 1, 0)[0] || null;
    },

    attentionBucketRemainingItems(bucket, offset = 1, limit = 3) {
      return this.attentionBucketItems(bucket, limit, offset);
    },

    attentionBucketDescription(bucket) {
      if (bucket === 'waiting_on_me') return 'Approvals, reviews, and decisions waiting on a human response.';
      if (bucket === 'watch') return 'Signals worth monitoring before they become urgent.';
      return 'Fresh issues and linked-system signals that deserve immediate attention.';
    },

    attentionBucketEmptyCopy(bucket) {
      if (bucket === 'waiting_on_me') return 'Nothing is blocked on you right now.';
      if (bucket === 'watch') return 'No slow-burn drift is being tracked right now.';
      return 'Nothing urgent is asking for attention right now.';
    },

    attentionBucketTone(bucket) {
      if (bucket === 'now') return 'border-rose-500/20 bg-rose-500/8 text-rose-200';
      if (bucket === 'waiting_on_me') return 'border-amber-500/20 bg-amber-500/8 text-amber-200';
      return 'border-cyan-500/20 bg-cyan-500/8 text-cyan-200';
    },

    attentionBucketPanelTone(bucket) {
      if (bucket === 'now') return 'border-rose-500/20 bg-[linear-gradient(180deg,rgba(76,5,25,0.28),rgba(2,6,23,0.78))]';
      if (bucket === 'waiting_on_me') return 'border-amber-500/20 bg-[linear-gradient(180deg,rgba(120,53,15,0.24),rgba(2,6,23,0.78))]';
      return 'border-cyan-500/20 bg-[linear-gradient(180deg,rgba(8,47,73,0.24),rgba(2,6,23,0.78))]';
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
      if (severity === 'critical' || severity === 'fatal') return 'border-rose-500/20 bg-rose-500/10 text-rose-100';
      if (severity === 'high') return 'border-amber-500/20 bg-amber-500/10 text-amber-100';
      if (severity === 'low') return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100';
      return 'border-slate-700 bg-slate-900/80 text-slate-300';
    },

    attentionSeverityLabel(item = {}) {
      return String(item?.severity || 'medium').trim().toLowerCase() || 'medium';
    },

    attentionCardTone(item = {}) {
      const severity = this.attentionSeverityLabel(item);
      if (severity === 'critical' || severity === 'fatal') return 'border-rose-500/25 bg-[linear-gradient(180deg,rgba(136,19,55,0.18),rgba(2,6,23,0.82))]';
      if (severity === 'high') return 'border-amber-500/25 bg-[linear-gradient(180deg,rgba(120,53,15,0.18),rgba(2,6,23,0.82))]';
      if (severity === 'low') return 'border-cyan-500/20 bg-[linear-gradient(180deg,rgba(8,47,73,0.16),rgba(2,6,23,0.82))]';
      return 'border-slate-700 bg-slate-950/72';
    },

    attentionItemAge(item = {}) {
      return this.timeAgo?.(item?.last_seen_at || item?.updated_at || item?.created_at) || 'recently';
    },

    attentionWorkspaceLabel(item = {}) {
      if (String(item?.project_name || '').trim()) return item.project_name;
      if (Number(item?.workspace_id || 0) > 0) return `Workspace #${item.workspace_id}`;
      return 'Global';
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
