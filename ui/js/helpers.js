/* ══════════════════════════════════════════════════════════════
   Axon — Helpers Module
   ══════════════════════════════════════════════════════════════ */

function axonHelpersMixin() {
  return {

    // ── Helpers ────────────────────────────────────────────────────
    escapeHtml(text = '') {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    },

    sanitizeRenderedHtml(html = '') {
      const template = document.createElement('template');
      template.innerHTML = html;
      const allowedTags = new Set([
        'A', 'ARTICLE', 'B', 'BLOCKQUOTE', 'BR', 'BUTTON', 'CODE', 'DEL', 'DIV', 'EM', 'H1', 'H2', 'H3', 'H4',
        'H5', 'H6', 'HR', 'I', 'LI', 'OL', 'P', 'PRE', 'S', 'SPAN', 'STRONG', 'TABLE', 'TBODY',
        'TD', 'TH', 'THEAD', 'TR', 'UL',
      ]);
      const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_ELEMENT);
      const toRemove = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!allowedTags.has(node.tagName)) {
          toRemove.push(node);
          continue;
        }
        [...node.attributes].forEach(attr => {
          const name = attr.name.toLowerCase();
          const value = attr.value || '';
          if (name.startsWith('on')) {
            node.removeAttribute(attr.name);
            return;
          }
          if (name === 'href') {
            if (!/^(https?:|mailto:|#)/i.test(value)) {
              node.removeAttribute(attr.name);
            } else {
              node.setAttribute('target', '_blank');
              node.setAttribute('rel', 'noopener noreferrer');
            }
            return;
          }
          // Allow class on CODE/SPAN for syntax highlighting (hljs-*)
          // Allow class on DIV/PRE/BUTTON for axon code blocks (axon-cb*)
          if (name === 'class') {
            const tag = node.tagName;
            if (tag === 'CODE' || tag === 'SPAN') {
              const safe = value.split(/\s+/).filter(c => /^(hljs|language-)/.test(c)).join(' ');
              if (safe) { node.setAttribute('class', safe); } else { node.removeAttribute('class'); }
              return;
            }
            if (tag === 'DIV' || tag === 'PRE' || tag === 'BUTTON') {
              const safe = value.split(/\s+/).filter(c => /^axon-cb/.test(c)).join(' ');
              if (safe) { node.setAttribute('class', safe); } else { node.removeAttribute('class'); }
              return;
            }
          }
          // Allow type/tabindex only on BUTTON (for code block copy)
          if ((name === 'type' || name === 'tabindex') && node.tagName === 'BUTTON') return;
          // Allow aria-hidden on DIV (line numbers)
          if (name === 'aria-hidden' && node.tagName === 'DIV') return;
          if (name !== 'href' && name !== 'colspan' && name !== 'rowspan') {
            node.removeAttribute(attr.name);
          }
        });
      }
      toRemove.forEach(node => node.replaceWith(...node.childNodes));
      return template.innerHTML;
    },

    renderMd(text) {
      if (!text || typeof marked === 'undefined') return text || '';
      if (!this._markdownConfigured) {
        // Use custom code block renderer (axon-codeblock) — handles hljs internally
        const codeRenderer = typeof this.getCodeBlockRenderer === 'function'
          ? this.getCodeBlockRenderer()
          : {};
        marked.use({
          gfm: true,
          breaks: true,
          renderer: codeRenderer,
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

    githubRepoMeta(data) {
      if (!data) return '';
      const parts = [];
      const branch = data?.repo?.defaultBranchRef?.name;
      const pushed = data?.repo?.pushedAt;
      if (branch) parts.push(`Default branch: ${branch}`);
      if (pushed) parts.push(`Last push: ${this.formatTime(pushed)}`);
      return parts.join(' · ');
    },

    githubCiStatus(data) {
      const latest = data?.ci?.latest || {};
      const state = latest?.conclusion || latest?.status || '';
      if (!state) return 'No CI data';
      if (state === 'success') return 'Passing';
      if (state === 'failure') return 'Failing';
      if (state === 'cancelled') return 'Cancelled';
      if (state === 'in_progress') return 'Running';
      if (state === 'queued' || state === 'pending' || state === 'requested' || state === 'waiting') return 'Queued';
      return state;
    },

    githubCiClass(data) {
      const latest = data?.ci?.latest || {};
      const state = latest?.conclusion || latest?.status || '';
      if (state === 'success') return 'text-green-400';
      if (state === 'failure') return 'text-red-400';
      if (state === 'cancelled' || state === 'in_progress' || state === 'queued' || state === 'pending') return 'text-yellow-400';
      return 'text-slate-400';
    },

    githubCiMeta(data) {
      const latest = data?.ci?.latest || {};
      if (!latest?.name) return 'No recent GitHub Actions run found for this repo.';
      const parts = [latest.name];
      if (latest.createdAt) parts.push(this.formatTime(latest.createdAt));
      return parts.join(' · ');
    },

    formatAge(days) {
      if (days == null) return 'no git';
      if (days < 1) return 'today';
      if (days < 2) return 'yesterday';
      if (days < 7) return Math.floor(days) + 'd ago';
      if (days < 30) return Math.floor(days/7) + 'w ago';
      return Math.floor(days/30) + 'mo ago';
    },

    isOverdue(date) {
      if (!date) return false;
      return new Date(date) < new Date();
    },

    healthColor(h) {
      if (h >= 80) return 'bg-green-500';
      if (h >= 60) return 'bg-yellow-500';
      if (h >= 40) return 'bg-orange-500';
      return 'bg-red-500';
    },

    healthTextColor(h) {
      if (h >= 80) return 'text-green-400';
      if (h >= 60) return 'text-yellow-400';
      if (h >= 40) return 'text-orange-400';
      return 'text-red-400';
    },

    iconSVG(id) {
      const icons = {
        dashboard: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M11.47 3.84a.75.75 0 011.06 0l8.69 8.69a.75.75 0 101.06-1.06l-8.69-8.69a2.25 2.25 0 00-3.18 0l-8.69 8.69a.75.75 0 001.06 1.06l8.69-8.69z"/><path d="M12 5.432l8.159 8.159c.03.03.06.058.091.086v6.198c0 1.035-.84 1.875-1.875 1.875H15a.75.75 0 01-.75-.75v-4.5a.75.75 0 00-.75-.75h-3a.75.75 0 00-.75.75V21a.75.75 0 01-.75.75H5.625a1.875 1.875 0 01-1.875-1.875v-6.198a2.29 2.29 0 00.091-.086L12 5.43z"/></svg>`,
        chat: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path fill-rule="evenodd" d="M4.804 21.644A6.707 6.707 0 006 21.75a6.721 6.721 0 003.583-1.029c.774.182 1.584.279 2.417.279 5.322 0 9.75-3.97 9.75-9 0-5.03-4.428-9-9.75-9s-9.75 3.97-9.75 9c0 2.409 1.025 4.587 2.674 6.192.232.226.277.428.254.543a3.73 3.73 0 01-.814 1.686.75.75 0 00.44 1.223 4.17 4.17 0 003-1.08z" clip-rule="evenodd"/></svg>`,
        projects: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path d="M19.906 9c.382 0 .749.057 1.094.162V9a3 3 0 00-3-3h-3.879a.75.75 0 01-.53-.22L11.47 3.66A2.25 2.25 0 009.879 3H6a3 3 0 00-3 3v3.162A3.756 3.756 0 014.094 9h15.812zM4.094 10.5a2.25 2.25 0 00-2.227 2.568l.857 6A2.25 2.25 0 004.951 21H19.05a2.25 2.25 0 002.227-1.932l.857-6a2.25 2.25 0 00-2.227-2.568H4.094z"/></svg>`,
        files: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path fill-rule="evenodd" d="M5.625 1.5H9a3.75 3.75 0 013.75 3.75v1.875c0 1.036.84 1.875 1.875 1.875H16.5a3.75 3.75 0 013.75 3.75v7.875c0 1.035-.84 1.875-1.875 1.875H5.625a1.875 1.875 0 01-1.875-1.875V3.375c0-1.036.84-1.875 1.875-1.875zM9.75 17.25a.75.75 0 00-1.5 0V18a.75.75 0 001.5 0v-.75zm2.25-3a.75.75 0 01.75.75v3a.75.75 0 01-1.5 0v-3a.75.75 0 01.75-.75zm3.75-1.5a.75.75 0 00-1.5 0V18a.75.75 0 001.5 0v-4.5z" clip-rule="evenodd"/><path d="M14.25 5.25a5.23 5.23 0 00-1.279-3.434 9.768 9.768 0 016.963 6.963A5.23 5.23 0 0016.5 7.5h-1.875a.375.375 0 01-.375-.375V5.25z"/></svg>`,
        more: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5"><path fill-rule="evenodd" d="M3 6.75A.75.75 0 013.75 6h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 6.75zM3 12a.75.75 0 01.75-.75h16.5a.75.75 0 010 1.5H3.75A.75.75 0 013 12zm0 5.25a.75.75 0 01.75-.75H12a.75.75 0 010 1.5H3.75a.75.75 0 01-.75-.75z" clip-rule="evenodd"/></svg>`,
      };
      return icons[id] || '';
    },

    inspectProject(projectId) {
      const project = (this.projects || []).find(item => Number(item.id) === Number(projectId));
      if (project) this.analyseProject(project);
    },

    openConsoleForProject(projectId) {
      const project = (this.projects || []).find(item => Number(item.id) === Number(projectId));
      if (project) this.openProjectChat(project);
    },

    statusBadge(s) {
      return { active: 'bg-green-900/40 text-green-400', paused: 'bg-yellow-900/40 text-yellow-400',
               done: 'bg-blue-900/40 text-blue-400', archived: 'bg-slate-800 text-slate-500' }[s] || 'bg-slate-800 text-slate-400';
    },

    priorityBadge(p) {
      return { urgent: 'bg-red-900/50 text-red-400', high: 'bg-orange-900/50 text-orange-400',
               medium: 'bg-yellow-900/40 text-yellow-400', low: 'bg-slate-800 text-slate-500' }[p] || '';
    },

    eventIcon(type) {
      return { scan:'🔄', chat:'💬', reminder:'⏰', digest:'☀️', task_added:'✅',
               prompt_saved:'📚', analysis:'🔍', vault:'🔐' }[type] || '📝';
    },

    timelineGroupLabel(type) {
      return {
        scan: 'scan',
        chat: 'agent',
        reminder: 'mission',
        digest: 'system',
        task_added: 'mission',
        prompt_saved: 'playbook',
        analysis: 'agent',
        vault: 'vault',
        maintenance: 'system',
        model: 'model',
      }[type] || String(type || 'system').replace(/_/g, ' ');
    },

    scanTriggerLabel(summary) {
      const text = String(summary || '');
      if (text.startsWith('Auto-scan (scheduled):')) return '🔄 Auto-scan (scheduled)';
      if (text.startsWith('Manual scan:')) return '👆 Manual scan';
      if (text.startsWith('Triggered scan:')) return '⚡ Triggered scan';
      return '🔄 Scan';
    },

    latestAutoScanAt() {
      const items = [...(this.activity || []), ...(this.dashRecentActivity || [])];
      const match = items.find(item => String(item?.event_type) === 'scan' && String(item?.summary || '').startsWith('Auto-scan (scheduled):'));
      return match?.created_at || '';
    },

    showToast(msg, duration=2500) {
      this.toast = { show: true, message: msg };
      setTimeout(() => this.toast.show = false, duration);
    },

    // Signature takes 4 explicit params so Alpine tracks each property change reactively.
    renderToolBlock(name, args, result, status) {
      const isRunning = status === 'running';
      args = args || {};
      result = result || '';

      const esc = (s) => String(s || '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

      const highlight = (code, lang) => {
        if (typeof hljs !== 'undefined') {
          if (lang && lang !== 'plaintext' && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
          }
          if (lang === 'plaintext') return esc(code);
          return hljs.highlightAuto(code).value;
        }
        return esc(code);
      };

      const extToLang = (path) => {
        const ext = String(path || '').split('.').pop().toLowerCase();
        return { js: 'javascript', ts: 'typescript', tsx: 'typescript', jsx: 'javascript',
                 py: 'python', sh: 'bash', bash: 'bash', html: 'html', css: 'css',
                 json: 'json', md: 'markdown', yml: 'yaml', yaml: 'yaml',
                 rs: 'rust', go: 'go', java: 'java', rb: 'ruby', php: 'php',
                 c: 'c', cpp: 'cpp', cs: 'csharp', sql: 'sql', toml: 'ini' }[ext] || 'plaintext';
      };

      // A flush section: divider + label bar + code
      const section = (code, lang, label, isInput) => {
        const highlighted = highlight(code, lang);
        const bg = isInput ? 'rgba(2,6,23,0.95)' : 'rgba(2,6,23,0.7)';
        const labelColor = isInput ? '#f59e0b' : '#475569';
        return `<div style="border-top:1px solid rgba(30,41,59,0.8)">` +
          `<div style="padding:3px 12px;background:rgba(2,6,23,0.55)">` +
          `<span style="font-size:9px;text-transform:uppercase;letter-spacing:.12em;color:${labelColor};font-family:monospace">${label}</span></div>` +
          `<pre style="margin:0;padding:8px 12px;font-size:11px;line-height:1.6;overflow-x:auto;overflow-y:auto;max-height:240px;background:${bg}">` +
          `<code class="hljs language-${esc(lang)}">${highlighted}</code></pre></div>`;
      };

      const pathRow = (p) => p
        ? `<div style="border-top:1px solid rgba(30,41,59,0.8);padding:4px 12px;background:rgba(2,6,23,0.55)">` +
          `<span style="font-size:10px;color:#64748b;font-family:monospace">${esc(p)}</span></div>`
        : '';

      const runningRow = () =>
        `<div style="border-top:1px solid rgba(30,41,59,0.8);padding:7px 12px;background:rgba(2,6,23,0.7)">` +
        `<span style="font-size:10px;color:#f59e0b;font-family:monospace;opacity:0.55">executing…</span></div>`;

      const successRow = (msg) =>
        `<div style="border-top:1px solid rgba(16,185,129,0.15);padding:5px 12px;background:rgba(6,78,59,0.2)">` +
        `<span style="font-size:10px;color:#34d399;font-family:monospace">✓ ${esc(msg)}</span></div>`;

      const approvalInlineNote = (title, subject, detail) => {
        const safeSubject = String(subject || '').trim();
        return `<div class="axon-approval-note">`
          + `<div class="axon-approval-note__header">`
          + `<span class="axon-approval-note__badge">Approval required</span>`
          + `<span class="axon-approval-note__title">${esc(title)}</span>`
          + `</div>`
          + (safeSubject ? `<code class="axon-approval-note__subject">${esc(safeSubject)}</code>` : '')
          + `<div class="axon-approval-note__detail">${esc(detail)}</div>`
          + `</div>`;
      };

      // Blocked file-edit gate UI — routed to the bottom composer approval dock
      const blockedEditHtml = (op, filePath) => {
        const shortPath = filePath.replace(/^\/home\/[^/]+/, '~').split('/').slice(-3).join('/');
        const opLabel = { write: 'Write', edit: 'Edit', delete: 'Delete', append: 'Append', create: 'Create' }[op] || op;
        return approvalInlineNote(
          `Axon is paused before it can ${opLabel.toLowerCase()} this file.`,
          shortPath,
          'Use the approval controls near the composer to continue the task from here.'
        );
      };

      let html = '';

      if (name === 'shell_cmd') {
        const cmd = args.cmd || args.command || '';
        if (cmd) html += section(cmd, 'bash', '$ command', true);
        // Detect blocked command — show approval UI instead of raw error
        if (result && result.startsWith('BLOCKED_CMD:')) {
          const parts = result.split(':');
          const blockedName = parts[1] || cmd.split(' ')[0];
          const fullCmd = parts.slice(2).join(':') || cmd;
          html += approvalInlineNote(
            'Axon is paused before it can run this command.',
            fullCmd || blockedName,
            'Use the approval controls near the composer to allow or deny this step without losing continuity.'
          );
        } else if (result) {
          html += section(result.slice(0, 1200), 'plaintext', 'output', false);
        } else if (isRunning && cmd) html += runningRow();

      } else if (name === 'shell_bg') {
        const cmd = args.cmd || args.command || '';
        if (cmd) html += section(cmd, 'bash', '$ background', true);
        if (result && result.startsWith('BLOCKED_CMD:')) {
          const parts = result.split(':');
          const blockedName = parts[1] || cmd.split(' ')[0];
          const fullCmd = parts.slice(2).join(':') || cmd || blockedName;
          html += approvalInlineNote(
            'Axon is paused before it can run this background command.',
            fullCmd,
            'Use the approval controls near the composer to continue the same task from here.'
          );
        } else if (result) html += section(result.slice(0, 2000), 'plaintext', 'process output', false);
        else if (isRunning && cmd) html += runningRow();

      } else if (name === 'shell_bg_check') {
        const pidLabel = args.pid ? `PID ${args.pid}` : 'process';
        if (result) html += section(result.slice(0, 2000), 'plaintext', pidLabel, false);
        else if (isRunning) html += runningRow();

      } else if (name === 'write_file' || name === 'edit_file' || name === 'delete_file' || name === 'append_file' || name === 'create_file') {
        const lang = extToLang(args.path || '');
        html += pathRow(args.path);
        if (result && result.startsWith('BLOCKED_EDIT:')) {
          const parts = result.split(':');
          const op = parts[1] || name.replace('_file', '');
          const filePath = parts.slice(2).join(':');
          html += blockedEditHtml(op, filePath);
        } else {
          if (name === 'write_file' && args.content) html += section(args.content, lang, lang !== 'plaintext' ? lang : 'content', true);
          if (name === 'edit_file' && args.old_string) html += section(`- ${args.old_string}\n+ ${args.new_string || ''}`, 'diff', 'diff', true);
          if (result) html += successRow(result.slice(0, 180));
          else if (isRunning) html += runningRow();
        }

      } else if (name === 'read_file') {
        const lang = extToLang(args.path || '');
        html += pathRow(args.path);
        if (result) html += section(result.slice(0, 1200), lang, lang !== 'plaintext' ? lang : 'file', false);
        else if (isRunning) html += runningRow();

      } else if (name === 'list_dir') {
        html += pathRow(args.path);
        if (result) html += section(result.slice(0, 800), 'plaintext', 'directory', false);
        else if (isRunning) html += runningRow();

      } else if (name === 'search_code' || name === 'search_files') {
        const query = args.query || args.pattern || args.q || '';
        if (query) html += pathRow('🔍 ' + query);
        if (result) html += section(result.slice(0, 800), 'plaintext', 'matches', false);
        else if (isRunning) html += runningRow();

      } else {
        if (Object.keys(args).length) {
          html += section(JSON.stringify(args, null, 2), 'json', name.replace(/_/g, ' '), true);
        }
        if (result) html += section(result.slice(0, 600), 'plaintext', 'result', false);
        else if (isRunning && Object.keys(args).length) html += runningRow();
      }

      return html;
    },

    toolPreview(name, args) {
      if (!name || !args) return '';
      if (name === 'shell_cmd' || name === 'shell_bg') return String(args.cmd || args.command || '').split('\n')[0].slice(0, 60);
      if (name === 'shell_bg_check') return args.pid ? `PID ${args.pid}` : '';
      if (name === 'write_file' || name === 'read_file') return String(args.path || '').split('/').slice(-2).join('/');
      if (name === 'list_dir') return String(args.path || '').replace(/^\/home\/[^/]+/, '~');
      if (name === 'search_code' || name === 'search_files') return String(args.query || args.pattern || '').slice(0, 50);
      const keys = Object.keys(args);
      return keys.length === 1 ? String(args[keys[0]] || '').slice(0, 50) : '';
    },

    /* ── Cowork sidebar: Progress Steps ── */
    coworkSteps() {
      const msgs = this.chatMessages || [];
      for (let i = msgs.length - 1; i >= 0; i--) {
        const msg = msgs[i];
        if (msg.role === 'assistant' && msg.workingBlocks?.length) {
          return msg.workingBlocks.map((b, idx) => ({
            num: idx + 1,
            label: this.prettyToolName(b.name),
            detail: this.toolPreview(b.name, b.args),
            status: b.status,
          }));
        }
      }
      return [];
    },

    /* ── Cowork sidebar: Working Files ── */
    coworkFiles() {
      const msgs = this.chatMessages || [];
      const fileMap = new Map();
      for (let i = msgs.length - 1; i >= 0; i--) {
        const msg = msgs[i];
        if (msg.role === 'assistant' && msg.workingBlocks?.length) {
          for (const b of msg.workingBlocks) {
            const a = b.args || {};
            const p = a.path || a.file_path || a.filepath || '';
            if (!p) continue;
            const act = (b.name === 'write_file' || b.name === 'edit_file') ? 'edited'
                      : b.name === 'read_file' ? 'read'
                      : b.name === 'list_dir' ? 'listed' : 'used';
            if (!fileMap.has(p) || act === 'edited') fileMap.set(p, act);
          }
          break;
        }
      }
      return [...fileMap.entries()].map(([path, action]) => ({
        path,
        short: path.replace(/^\/home\/[^/]+/, '~').split('/').slice(-3).join('/'),
        action,
      }));
    },

  };
}

window.axonHelpersMixin = axonHelpersMixin;
