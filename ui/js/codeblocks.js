/* ══════════════════════════════════════════════════════════════
   Axon — Code Blocks Module
   Streaming-friendly code blocks with header, language badge,
   line numbers, and copy button. Inspired by Anthropic's
   Claude code blocks, enhanced for Axon.
   ══════════════════════════════════════════════════════════════ */

function axonCodeblocksMixin() {
  return {

    /* ── Initialization ─────────────────────────────────────── */

    initCodeblocks() {
      // Delegate click on copy buttons (works for dynamically rendered content)
      document.addEventListener('click', (e) => {
        const btn = e.target.closest('.axon-cb-copy');
        if (!btn) return;
        const wrapper = btn.closest('.axon-codeblock');
        if (!wrapper) return;
        const codeEl = wrapper.querySelector('pre code');
        if (!codeEl) return;
        const text = codeEl.textContent || '';
        navigator.clipboard.writeText(text).then(() => {
          btn.dataset.copied = '1';
          btn.textContent = 'Copied!';
          setTimeout(() => {
            btn.dataset.copied = '';
            btn.textContent = 'Copy';
          }, 2000);
        }).catch(() => {});
      });
    },

    /* ── Custom marked renderer for code blocks ─────────────── */

    getCodeBlockRenderer() {
      return {
        code({ text, lang, escaped }) {
          const language = (lang || '').split(/\s/)[0] || '';
          const displayLang = language ? _codeblockLangLabel(language) : 'text';

          // Highlight with hljs if available
          let highlighted = '';
          if (typeof hljs !== 'undefined' && language && hljs.getLanguage(language)) {
            highlighted = hljs.highlight(text, { language }).value;
          } else if (typeof hljs !== 'undefined') {
            highlighted = hljs.highlightAuto(text).value;
          } else {
            highlighted = _escapeCodeHtml(text);
          }

          // Line numbers
          const lines = text.split('\n');
          const lineCount = lines.length;
          const lineNums = lines.map((_, i) =>
            `<span class="axon-cb-ln">${i + 1}</span>`
          ).join('\n');

          return (
            `<div class="axon-codeblock">` +
              `<div class="axon-cb-header">` +
                `<span class="axon-cb-lang">${_escapeCodeHtml(displayLang)}</span>` +
                `<span class="axon-cb-spacer"></span>` +
                `<button type="button" class="axon-cb-copy" tabindex="-1">Copy</button>` +
              `</div>` +
              `<div class="axon-cb-body">` +
                `<div class="axon-cb-lines" aria-hidden="true">${lineNums}</div>` +
                `<pre class="axon-cb-pre"><code class="hljs language-${_escapeCodeHtml(language)}">${highlighted}</code></pre>` +
              `</div>` +
            `</div>`
          );
        }
      };
    },

  };
}

/* ── Private helpers (module-scoped) ───────────────────────── */

function _escapeCodeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const _LANG_LABELS = {
  js: 'JavaScript', javascript: 'JavaScript', ts: 'TypeScript', typescript: 'TypeScript',
  py: 'Python', python: 'Python', rb: 'Ruby', ruby: 'Ruby',
  rs: 'Rust', rust: 'Rust', go: 'Go', java: 'Java',
  cpp: 'C++', 'c++': 'C++', c: 'C', cs: 'C#', csharp: 'C#',
  sh: 'Shell', bash: 'Bash', zsh: 'Zsh', fish: 'Fish',
  html: 'HTML', css: 'CSS', scss: 'SCSS', less: 'LESS',
  json: 'JSON', yaml: 'YAML', yml: 'YAML', toml: 'TOML',
  xml: 'XML', sql: 'SQL', graphql: 'GraphQL',
  md: 'Markdown', markdown: 'Markdown',
  dockerfile: 'Dockerfile', docker: 'Docker',
  swift: 'Swift', kotlin: 'Kotlin', kt: 'Kotlin',
  php: 'PHP', lua: 'Lua', r: 'R', julia: 'Julia',
  elixir: 'Elixir', ex: 'Elixir', erl: 'Erlang',
  zig: 'Zig', nim: 'Nim', dart: 'Dart',
  text: 'Plain Text', txt: 'Plain Text', plaintext: 'Plain Text',
  diff: 'Diff', powershell: 'PowerShell', ps1: 'PowerShell',
  ini: 'INI', conf: 'Config', makefile: 'Makefile',
  vue: 'Vue', svelte: 'Svelte', jsx: 'JSX', tsx: 'TSX',
};

function _codeblockLangLabel(lang) {
  return _LANG_LABELS[lang.toLowerCase()] || lang;
}
