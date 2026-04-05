/* ══════════════════════════════════════════════════════════════
   Axon - Console Guidance
   ══════════════════════════════════════════════════════════════ */

function axonConsoleGuidanceMixin() {
  const normalize = (value) => String(value || '').trim();

  return {
    consolePrimaryModeMeta() {
      const mode = normalize(this.activePrimaryConversationMode?.() || 'ask').toLowerCase() || 'ask';
      const workspace = normalize(this.chatProject?.name || this.workspaceTabLabel?.(this.chatProjectId || ''));
      const branch = normalize(this.currentWorkspaceBranchName?.() || '');
      const workspaceLabel = workspace || 'your next workspace';
      const branchLabel = branch || 'active branch';

      const meta = {
        ask: {
          kicker: 'Operator command lane',
          label: 'Direct control',
          summary: workspace
            ? `You are steering ${workspaceLabel} directly. Axon will inspect, explain, and execute on command.`
            : 'Pick a workspace and steer the next move directly from the command ring.',
        },
        auto: {
          kicker: 'Autonomous execution lane',
          label: 'Autonomous mode',
          summary: workspace
            ? `Axon can continue ${workspaceLabel} on ${branchLabel}, verify work, and recover when the task is actionable.`
            : 'Axon can observe, execute, verify, and recover on actionable local work.',
        },
        agent: {
          kicker: 'Local tools armed',
          label: '#NEXT-GEN agent',
          summary: workspace
            ? `Axon is armed for local-tool work inside ${workspaceLabel} while you remain in command of each next step.`
            : 'Arm local tools for repo inspection, files, terminals, and guided execution.',
        },
        code: {
          kicker: 'Engineering lane',
          label: 'Code execution',
          summary: workspace
            ? `Focus ${workspaceLabel} on code understanding, patch planning, and implementation work.`
            : 'Use the code lane for source inspection, patches, and technical verification.',
        },
        research: {
          kicker: 'Deep research lane',
          label: 'Research mode',
          summary: workspace
            ? `Push ${workspaceLabel} through broader analysis, tradeoffs, and evidence gathering before action.`
            : 'Use research mode when the next move needs broader evidence before execution.',
        },
        business: {
          kicker: 'Business operations lane',
          label: 'Business dock',
          summary: 'Generate invoices, quotes, client follow-ups, and operator-facing business documents.',
        },
      };

      return meta[mode] || meta.ask;
    },

    consoleAutonomyCard() {
      const workspace = normalize(this.chatProject?.name || this.workspaceTabLabel?.(this.chatProjectId || ''));
      const runtimeReady = !!this.currentBackendSupportsAgent?.();
      const active = !!this.autonomousConsoleActive?.();
      const resumable = !!this.currentWorkspaceAutoSession?.();

      if (!runtimeReady) {
        return {
          title: 'Autonomous mode locked',
          detail: 'Switch the runtime to CLI Agent or Ollama-backed local tools to arm Autonomous mode.',
          badge: 'Locked',
          cardClass: 'console-autonomy-card console-autonomy-card-locked',
          badgeClass: 'console-autonomy-badge console-autonomy-badge-locked',
        };
      }

      if (active) {
        return {
          title: 'Autonomous mode armed',
          detail: workspace
            ? `Axon is cleared to keep ${workspace} moving with observation, execution, verification, and recovery.`
            : 'Axon is cleared to keep actionable local work moving with observation, execution, verification, and recovery.',
          badge: 'Armed',
          cardClass: 'console-autonomy-card console-autonomy-card-armed',
          badgeClass: 'console-autonomy-badge console-autonomy-badge-armed',
        };
      }

      if (resumable) {
        return {
          title: 'Autonomous lane ready',
          detail: workspace
            ? `A resumable autonomous run exists for ${workspace}. Re-arm the lane to continue from the latest safe checkpoint.`
            : 'A resumable autonomous run is available. Re-arm the lane to continue from the latest safe checkpoint.',
          badge: 'Ready',
          cardClass: 'console-autonomy-card console-autonomy-card-ready',
          badgeClass: 'console-autonomy-badge console-autonomy-badge-ready',
        };
      }

      return {
        title: 'Autonomous mode',
        detail: workspace
          ? `Let Axon inspect ${workspace}, execute safe local steps, and keep proof-of-work flowing when the task is actionable.`
          : 'Let Axon observe, execute, verify, and recover when the task is actionable.',
        badge: 'Standby',
        cardClass: 'console-autonomy-card console-autonomy-card-standby',
        badgeClass: 'console-autonomy-badge console-autonomy-badge-standby',
      };
    },

    toggleAutonomousConsoleMode() {
      if (!this.currentBackendSupportsAgent?.()) {
        this.switchTab?.('settings');
        return;
      }
      if (this.autonomousConsoleActive?.()) {
        this.chooseConversationModeAsk?.();
        return;
      }
      this.chooseConversationModeAuto?.();
    },

    consoleQuickStartHints() {
      const workspace = normalize(this.chatProject?.name || this.workspaceTabLabel?.(this.chatProjectId || ''));
      const branch = normalize(this.currentWorkspaceBranchName?.() || '');
      const branchLabel = branch || 'active branch';
      const workspaceLabel = workspace || 'the selected workspace';
      const prompts = [];

      if (!workspace) {
        prompts.push(
          {
            label: 'Review active runs',
            detail: 'Find resumable sessions, blockers, and proofs of work.',
            prompt: 'Review active runs across all workspaces, show blockers, and recommend which workspace needs attention first.',
          },
          {
            label: 'Check approvals',
            detail: 'Surface everything waiting on operator approval.',
            prompt: 'Check pending approvals across all workspaces and summarize what is blocked, by workspace.',
          },
          {
            label: 'Choose a workspace',
            detail: 'Compare branches, runtime readiness, and open risk.',
            prompt: 'Compare the active workspaces, their current branches, and runtime readiness, then recommend which workspace to open next and why.',
          },
        );
        if (this.currentBackendSupportsAgent?.()) {
          prompts.push({
            label: 'Arm autonomous lane',
            detail: 'Prepare the best workspace for autonomous execution.',
            prompt: 'Review active workspaces and prepare the best candidate for Autonomous mode, including the next safe step.',
          });
        }
        return prompts.slice(0, 4);
      }

      prompts.push(
        {
          label: 'Map workspace',
          detail: `Inspect ${workspaceLabel}, ${branchLabel}, and current risk.`,
          prompt: `Inspect workspace ${workspaceLabel} on ${branchLabel} and summarize the architecture, branch state, blockers, and next actions.`,
        },
        {
          label: 'Check branch',
          detail: `Audit ${branchLabel} for drift, risky edits, and missing verification.`,
          prompt: `Inspect branch ${branchLabel} in workspace ${workspaceLabel}, summarize recent changes, risky files, and what needs verification next.`,
        },
        {
          label: 'Review approvals',
          detail: 'Find anything blocked on operator attention.',
          prompt: `Check pending approvals for workspace ${workspaceLabel} and tell me exactly what is blocked or ready to continue.`,
        },
      );

      if (this.currentBackendSupportsAgent?.()) {
        prompts.push(
          this.autonomousConsoleActive?.()
            ? {
                label: 'Continue autonomous lane',
                detail: 'Resume the current autonomous run and report the next safe step.',
                prompt: `Continue the active autonomous run for workspace ${workspaceLabel} and report the next safe step with proof of work.`,
              }
            : {
                label: 'Arm autonomous lane',
                detail: 'Let Axon observe, execute, verify, and recover for this workspace.',
                prompt: `Start an autonomous run for workspace ${workspaceLabel}: observe the repo, identify blockers, and prepare the next safe execution step.`,
              }
        );
      }

      return prompts.slice(0, 4);
    },
  };
}

window.axonConsoleGuidanceMixin = axonConsoleGuidanceMixin;
