/* ══════════════════════════════════════════════════════════════
   Axon — Live Operator Runtime
   ══════════════════════════════════════════════════════════════ */

function axonLiveOperatorMixin() {
  const scopedWorkspaceId = (ctx, workspaceId = null) => String(
    workspaceId == null ? (ctx.chatProjectId || '') : workspaceId,
  ).trim();

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
    }
  };

  return {
    currentWorkspaceLiveOperatorVisible() {
      return !!this.currentWorkspaceRunActive?.() || !!this.liveOperator?.active;
    },

    beginLiveOperator(mode = 'chat', msg = '', workspaceId = null) {
      const target = scopedWorkspaceId(this, workspaceId);
      const operator = this.beginWorkspaceLiveOperator?.(target, mode, msg);
      if (mode === 'agent') this.setAgentStage?.('observe');
      if (String(this.chatProjectId || '').trim() === target && this.desktopPreview?.enabled) {
        this.refreshDesktopPreview?.(true);
        this.scheduleDesktopPreview?.();
      }
      return operator;
    },

    updateLiveOperator(mode = 'chat', event = {}, workspaceId = null) {
      const target = scopedWorkspaceId(this, workspaceId);
      if (!this.patchWorkspaceLiveOperator || !this.pushWorkspaceLiveOperatorFeed) return;

      if (!scopedOperator(this, target)?.active) {
        this.beginLiveOperator(mode, '', target);
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

      if (event.type === 'tool_call') {
        const detail = event.args ? JSON.stringify(event.args).slice(0, 96) : 'Using a local operator tool.';
        const title = `Running ${this.prettyToolName(event.name)}`;
        patchOperator(this, target, {
          active: true,
          phase: 'execute',
          title,
          detail,
          tool: event.name || '',
        }, {
          phase: 'execute',
          title,
          detail,
        });
        return;
      }
      if (event.type === 'tool_result') {
        const detail = (event.result || 'Axon is reviewing the tool output.').slice(0, 120);
        const title = `Checking ${this.prettyToolName(event.name)}`;
        patchOperator(this, target, {
          active: true,
          phase: 'verify',
          title,
          detail,
          tool: event.name || current.tool || '',
        }, {
          phase: 'verify',
          title,
          detail,
        });
        return;
      }
      if (event.type === 'text') {
        const phase = current.tool ? 'verify' : 'plan';
        const title = current.tool ? 'Writing the result' : 'Planning the next step';
        const detail = current.tool
          ? 'Axon is turning tool output into a final answer.'
          : 'Axon is reasoning through the task before it acts.';
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
