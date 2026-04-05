/* ══════════════════════════════════════════════════════════════
   Axon — Blocker Detection & Fix Suggestions
   Scans assistant messages for common blockers and surfaces
   one-click fix suggestions in Stark-tech blocker cards.
   ══════════════════════════════════════════════════════════════ */

function axonBlockerSuggestionsMixin() {
  return {
    /* ── Blocker pattern library ──────────────────────────────── */
    _blockerPatterns: [
      {
        id: 'module_not_found',
        pattern: /ModuleNotFoundError:\s*No module named ['"]([^'"]+)['"]/i,
        title: (m) => `Missing Python module: ${m[1]}`,
        fixes: (m) => [
          { label: `Install ${m[1]}`, command: `pip install ${m[1].replace(/_/g, '-')}` },
          { label: 'Check virtual env', command: 'which python && pip list' },
        ],
      },
      {
        id: 'npm_not_found',
        pattern: /Cannot find module ['"]([^'"]+)['"]/i,
        title: (m) => `Missing Node module: ${m[1]}`,
        fixes: (m) => [
          { label: `Install ${m[1]}`, command: `npm install ${m[1]}` },
          { label: 'Reinstall deps', command: 'rm -rf node_modules && npm install' },
        ],
      },
      {
        id: 'permission_denied',
        pattern: /Permission\s*denied|EACCES|PermissionError/i,
        title: () => 'Permission denied',
        fixes: () => [
          { label: 'Check file permissions', command: 'ls -la' },
          { label: 'Fix ownership', command: 'sudo chown -R $USER:$USER .' },
        ],
      },
      {
        id: 'port_in_use',
        pattern: /(?:EADDRINUSE|Address already in use|port\s+\d+\s+(?:is\s+)?(?:already\s+)?in\s+use)/i,
        title: () => 'Port already in use',
        fixes: () => [
          { label: 'Find process', command: 'lsof -i :PORT | head -5' },
          { label: 'Kill process on port', command: 'fuser -k PORT/tcp' },
        ],
      },
      {
        id: 'connection_refused',
        pattern: /Connection\s*refused|ECONNREFUSED|ConnectionRefusedError/i,
        title: () => 'Connection refused',
        fixes: () => [
          { label: 'Check if service is running', command: 'systemctl status' },
          { label: 'Test connection', command: 'curl -v localhost:PORT' },
        ],
      },
      {
        id: 'syntax_error',
        pattern: /SyntaxError:\s*(.+?)(?:\n|$)/i,
        title: (m) => `Syntax error: ${m[1].substring(0, 60)}`,
        fixes: () => [
          { label: 'Lint file', command: 'python3 -m py_compile FILE' },
        ],
      },
      {
        id: 'disk_space',
        pattern: /No space left on device|ENOSPC|disk\s+(?:full|space)/i,
        title: () => 'Disk space exhausted',
        fixes: () => [
          { label: 'Check free space', command: 'df -h' },
          { label: 'Find large files', command: 'du -sh * | sort -rh | head -10' },
        ],
      },
      {
        id: 'timeout',
        pattern: /timeout|timed?\s*out|ETIMEDOUT|deadline\s+exceeded/i,
        title: () => 'Operation timed out',
        fixes: () => [
          { label: 'Check network', command: 'ping -c 3 8.8.8.8' },
          { label: 'Retry with verbose', command: 'curl -v --max-time 30 URL' },
        ],
      },
      {
        id: 'git_conflict',
        pattern: /CONFLICT\s*\(|merge conflict|Automatic merge failed/i,
        title: () => 'Git merge conflict',
        fixes: () => [
          { label: 'Show conflicts', command: 'git diff --name-only --diff-filter=U' },
          { label: 'Abort merge', command: 'git merge --abort' },
        ],
      },
      {
        id: 'oom',
        pattern: /Out of memory|MemoryError|OOMKilled|Cannot allocate memory/i,
        title: () => 'Out of memory',
        fixes: () => [
          { label: 'Check memory', command: 'free -h' },
          { label: 'Top processes', command: 'ps aux --sort=-%mem | head -10' },
        ],
      },
    ],

    /* ── Scan a message for blockers ──────────────────────────── */
    detectBlockers(content) {
      if (!content) return [];
      const found = [];
      for (const bp of this._blockerPatterns) {
        const match = bp.pattern.exec(content);
        if (match) {
          found.push({
            id: bp.id,
            title: bp.title(match),
            fixes: bp.fixes(match),
          });
        }
      }
      return found;
    },

    /* ── Apply a fix suggestion (populate composer) ───────────── */
    applyFixSuggestion(command) {
      this.chatInput = command;
      this.$nextTick(() => {
        const el = this.$refs.chatComposer;
        if (el) {
          el.focus();
          el.style.height = 'auto';
          el.style.height = el.scrollHeight + 'px';
        }
      });
    },

    /* ── Check if message has blockers ────────────────────────── */
    messageBlockers(msg) {
      if (msg.role !== 'assistant') return [];
      if (msg._blockers !== undefined) return msg._blockers;
      msg._blockers = this.detectBlockers(msg.content);
      return msg._blockers;
    },
  };
}

window.axonBlockerSuggestionsMixin = axonBlockerSuggestionsMixin;
