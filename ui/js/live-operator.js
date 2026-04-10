/* ══════════════════════════════════════════════════════════════
   Axon — Live Operator Runtime
   ══════════════════════════════════════════════════════════════ */

function axonLiveOperatorMixin() {
  const LIVE_OPERATOR_TEXT_PREVIEW_LIMIT = 180;
  const scopedWorkspaceId = (ctx, workspaceId = null) => String(
    workspaceId == null ? (ctx.chatProjectId || '') : workspaceId,
  ).trim();
  const SAFE_PATH_PREFIXES = ['~/', './', '../', '/home/'];
  const trimText = (value = '') => String(value || '').trim();
  const clipText = (value = '', max = LIVE_OPERATOR_TEXT_PREVIEW_LIMIT) => {
    const text = trimText(value);
    return text.length > max ? `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…` : text;
  };
  const looksLikeLocalPath = (value = '') => {
    const raw = trimText(value);
    if (!raw) return false;
    return SAFE_PATH_PREFIXES.some(prefix => raw.startsWith(prefix));
  };
  const extractLocalPathsFromText = (value = '') => {
    const matches = String(value || '').match(/(?:~\/|\/|\.{1,2}\/)[^\s"'`<>]+/g) || [];
    return matches.map(v => String(v || '').replace(/[),.;:!?]+$/g, '')).filter(looksLikeLocalPath);
  };
  const safeDecode = (value = '') => {
    try { return decodeURIComponent(value); } catch (_) { return value; }
  };
  const extractPreviewablePathsFromText = (value = '') => {
    const localPaths = extractLocalPathsFromText(value);
    const openPaths = [
      ...String(value || '').matchAll(/\/api\/files\/open\?path=([^)&\s]+)/g),
    ].map(match => safeDecode(match?.[1] || '')).filter(looksLikeLocalPath);
    return [...new Set([...localPaths, ...openPaths])];
  };
  const parseToolArgs = (args) => {
    if (!args) return {};
    if (typeof args === 'object') return args;
    if (typeof args === 'string') {
      try {
        const parsed = JSON.parse(args);
        if (parsed && typeof parsed === 'object') return parsed;
      } catch (_) {}
      return { _raw: args };
    }
    return {};
  };
  const extractToolContext = (event = {}) => {
    const ctx = { paths: [], query: '' };
    const args = parseToolArgs(event.args);
    const pushPath = (value) => {
      if (!value) return;
      if (looksLikeLocalPath(value)) ctx.paths.push(value);
    };
    const scanKeys = (node = {}, key = '') => {
      if (!node || typeof node !== 'object') return;
      Object.entries(node).forEach(([k, v]) => {
        const lower = String(k || '').toLowerCase();
        if (typeof v === 'string') {
          if (/(^|_)(path|file|cwd|workdir|dir|root|base|workspace_path|source_workspace_path)$/.test(lower)) {
            pushPath(v);
          }
          if (/(query|pattern|needle|search|filename)$/i.test(lower) && !ctx.query) {
            ctx.query = trimText(v);
          }
          extractLocalPathsFromText(v).forEach(pushPath);
          return;
        }
        if (Array.isArray(v)) {
          v.forEach(item => {
            if (typeof item === 'string') {
              if (!ctx.query && /search|query|pattern|needle/.test(lower)) ctx.query = trimText(item);
              pushPath(item);
              extractLocalPathsFromText(item).forEach(pushPath);
            } else {
              scanKeys(item, lower);
            }
          });
          return;
        }
        if (v && typeof v === 'object') scanKeys(v, lower);
      });
    };
    scanKeys(args);
    if (args._raw && typeof args._raw === 'string') {
      extractLocalPathsFromText(args._raw).forEach(path => ctx.paths.push(path));
    }
    ctx.paths = [...new Set(ctx.paths)];
    return ctx;
  };

  const scopedOperator = (ctx, workspaceId = null) => {
    const target = scopedWorkspaceId(ctx, workspaceId);
    return ctx.workspaceRunStateFor?.(target)?.liveOperator || ctx.liveOperator || {};
  };

  const patchOperator = (ctx, workspaceId, patch, feed = null) => {
    ctx.patchWorkspaceLiveOperator?.(workspaceId, {
      ...patch,
      updatedAt: new Date().toISOString(),
    });
    if (feed) {
      ctx.pushWorkspaceLiveOperatorFeed?.(
        workspaceId,
        feed.phase,
        feed.title,
        feed.detail,
      );
      // JARVIS narration: speak brief status update during agent work
      if (typeof ctx.narrateAgentStep === 'function') {
        try { ctx.narrateAgentStep(feed.phase, feed.title, feed.detail); } catch (_) {}
      }
      // Push to live activity feed for JARVIS-style stream
      if (typeof ctx.pushActivityEntry === 'function') {
        try {
          ctx.pushActivityEntry(feed.phase, feed.title, feed.detail, {
            tool: patch?.tool,
            filePath: patch?.filePath || '',
          });
        } catch (_) {}
      }
    }
    // Sync secondary voice surfaces after the operator state is patched so
    // they observe the latest phase/title/feed rather than the previous step.
    ctx.syncVoiceCommandCenterRuntime?.();
    ctx.syncVoiceSurfaceDirector?.();
  };

  return {
    currentWorkspaceLiveOperatorVisible() {
      return !!this.currentWorkspaceRunActive?.() || !!this.liveOperator?.active;
    },

    beginLiveOperator(mode = 'chat', msg = '', workspaceId = null) {
      const target = scopedWorkspaceId(this, workspaceId);
      // Clear the activity feed on new task start
      if (typeof this.clearActivityFeed === 'function') this.clearActivityFeed();
      this.resetVoiceFileRevealState?.({ closeViewer: true });
      this.clearVoiceSurfaceHistory?.(false);
      const operator = this.beginWorkspaceLiveOperator?.(target, mode, msg);
      this.hudResetOperatorTrace?.(mode === 'agent' ? 'Live operator telemetry' : 'Reply telemetry');
      if (mode === 'agent') this.setAgentStage?.('observe');
      if (String(this.chatProjectId || '').trim() === target && this.desktopPreview?.enabled) {
        this.refreshDesktopPreview?.(true);
        this.scheduleDesktopPreview?.();
      }
      if (mode === 'agent') {
        this.maybeFollowWorkspacePreview?.({ mode, workspaceId: target });
      }
      return operator;
    },

    updateLiveOperator(mode = 'chat', event = {}, workspaceId = null) {
      const target = scopedWorkspaceId(this, workspaceId);
      if (!this.patchWorkspaceLiveOperator || !this.pushWorkspaceLiveOperatorFeed) return;

      if (!scopedOperator(this, target)?.active) {
        this.beginLiveOperator(mode, '', target);
      }

      if (typeof this.hudProcessAgentEvent === 'function') {
        try { this.hudProcessAgentEvent(event); } catch (_) {}
      }
      const current = scopedOperator(this, target);
      if (mode !== 'agent') {
        if (event.error) {
          patchOperator(this, target, {
            active: true,
            phase: 'recover',
            title: 'Reply interrupted',
            detail: event.error,
          }, {
            phase: 'recover',
            title: 'Reply interrupted',
            detail: event.error,
          });
          return;
        }
        if (event.done) {
          patchOperator(this, target, {
            active: true,
            phase: 'verify',
            title: 'Reply complete',
            detail: 'Axon finished streaming the answer.',
          }, {
            phase: 'verify',
            title: 'Reply complete',
            detail: 'Axon finished streaming the answer.',
          });
          return;
        }
        patchOperator(this, target, {
          active: true,
          phase: 'execute',
          title: 'Writing the reply',
          detail: 'Live response is flowing into the console now.',
        }, {
          phase: 'execute',
          title: 'Writing the reply',
          detail: 'Live response is flowing into the console now.',
        });
        return;
      }

      if (event.type === 'thinking') {
        const detail = clipText(
          event.chunk
          || current.detail
          || 'Axon is analysing the request and forming a plan.',
        );
        patchOperator(this, target, {
          active: true,
          phase: 'plan',
          title: trimText(current.title) || 'Thinking through the task',
          detail,
        }, {
          phase: 'plan',
          title: trimText(current.title) || 'Thinking through the task',
          detail,
        });
        return;
      }

      if (event.type === 'tool_call') {
        const toolSlug = String(event.name || '').toLowerCase();
        const toolContext = extractToolContext(event);
        const isSearchTool = /search|find|rg|ripgrep|glob|scan/.test(toolSlug);
        const isBrowseTool = /files\/browse|list|dir|ls/.test(toolSlug);
        const isReadTool = /files\/read|files\/open|open|read/.test(toolSlug);
        const workspacePath = trimText(
          this.currentWorkspaceAutoSession?.()?.source_workspace_path
          || this.currentWorkspaceAutoSession?.()?.workspace_path
          || this.chatProject?.path
          || this.browserSourcePath?.()
        );
        let detail = event.args ? JSON.stringify(event.args).slice(0, 96) : 'Using a local operator tool.';
        if (isSearchTool && (toolContext.query || workspacePath)) {
          detail = toolContext.query
            ? `Searching for "${toolContext.query}"${workspacePath ? ` in ${workspacePath}` : ''}.`
            : `Searching the workspace in ${workspacePath}.`;
        } else if ((isBrowseTool || isReadTool) && toolContext.paths.length) {
          detail = `${this.prettyToolName(event.name)} ${toolContext.paths[0]}`;
        }
        const title = isSearchTool
          ? 'Searching files'
          : isBrowseTool
            ? 'Browsing folders'
            : isReadTool
              ? 'Opening file'
              : `Running ${this.prettyToolName(event.name)}`;
        patchOperator(this, target, {
          active: true,
          phase: 'execute',
          title,
          detail,
          tool: event.name || '',
          filePath: toolContext.paths[0] || (isSearchTool ? workspacePath : ''),
        }, {
          phase: 'execute',
          title,
          detail,
        });
        if (this.showVoiceOrb && !this.voiceTerminalAutoDockActive?.()) {
          const autoPaths = (isBrowseTool || isReadTool) ? toolContext.paths : [];
          if (autoPaths.length) {
            const kind = isBrowseTool || isSearchTool ? 'folder' : '';
            this.queueVoiceFileReveal?.(autoPaths, { kind, maxItems: 3, delayMs: 900 });
          }
        }
        return;
      }
      if (event.type === 'tool_result') {
        const toolSlug = String(event.name || '').toLowerCase();
        const isSearchTool = /search|find|rg|ripgrep|glob|scan/.test(toolSlug);
        const isBrowseTool = /files\/browse|list|dir|ls/.test(toolSlug);
        const isReadTool = /files\/read|files\/open|open|read/.test(toolSlug);
        const resultText = typeof event.result === 'string'
          ? event.result
          : JSON.stringify(event.result || '');
        const resultPaths = extractPreviewablePathsFromText(resultText)
          .map(path => this._normalizeRevealPath?.(path) || path)
          .filter(Boolean);
        const queued = [...new Set(resultPaths)];
        if (this.showVoiceOrb && queued.length && !this.voiceTerminalAutoDockActive?.()) {
          const kind = isBrowseTool ? 'folder' : (isSearchTool ? '' : (isReadTool ? '' : ''));
          this.queueVoiceFileReveal?.(queued, { kind, maxItems: 6, delayMs: 1000 });
        }
        const detail = (event.result || 'Axon is reviewing the tool output.').slice(0, 120);
        const title = `Checking ${this.prettyToolName(event.name)}`;
        patchOperator(this, target, {
          active: true,
          phase: 'verify',
          title,
          detail,
          tool: event.name || current.tool || '',
          filePath: queued[0] || '',
        }, {
          phase: 'verify',
          title,
          detail,
        });
        return;
      }
      if (event.type === 'text') {
        const streamedPaths = extractPreviewablePathsFromText(event.chunk || event.content || '')
          .map(path => this._normalizeRevealPath?.(path) || path)
          .filter(Boolean);
        if (this.showVoiceOrb && streamedPaths.length && !this.voiceTerminalAutoDockActive?.()) {
          this.queueVoiceFileReveal?.(streamedPaths, { maxItems: 4, delayMs: 850 });
        }
        const detail = clipText(
          event.chunk
          || event.content
          || (current.tool
            ? 'Axon is turning tool output into a final answer.'
            : 'Axon is drafting the answer now.'),
        );
        const phase = 'verify';
        const title = 'Writing the result';
        patchOperator(this, target, {
          active: true,
          phase,
          title,
          detail,
        }, {
          phase,
          title,
          detail,
        });
        return;
      }
      if (event.type === 'done') {
        patchOperator(this, target, {
          active: true,
          phase: 'verify',
          title: 'Task complete',
          detail: 'Axon finished the operator pass.',
        }, {
          phase: 'verify',
          title: 'Task complete',
          detail: 'Axon finished the operator pass.',
        });
        return;
      }
      if (event.type === 'error') {
        const detail = event.message || 'Axon hit an error and stopped safely.';
        patchOperator(this, target, {
          active: true,
          phase: 'recover',
          title: 'Needs attention',
          detail,
        }, {
          phase: 'recover',
          title: 'Needs attention',
          detail,
        });
      }

    },

    clearLiveOperator(delay = 0, workspaceId = null) {
      const target = scopedWorkspaceId(this, workspaceId);
      this.clearWorkspaceLiveOperator?.(target, delay);
    },
  };
}

window.axonLiveOperatorMixin = axonLiveOperatorMixin;
