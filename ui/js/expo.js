/* ══════════════════════════════════════════════════════════════
   Axon — Expo / EAS Surfaces
   ══════════════════════════════════════════════════════════════ */

function axonExpoMixin() {
  return {
    expoOverview: {
      status: 'unknown',
      summary: '',
      updated_at: '',
      projects: [],
      builds: [],
    },
    expoProjectSummaries: {},
    expoProjectBuilds: {},
    deliveryActivity: {
      updated_at: '',
      items: [],
      expo_active_builds: [],
      vercel_pending_actions: [],
      vercel_recent_actions: [],
    },
    expoLoading: false,
    expoActionLoading: false,
    expoError: '',
    expoLastAction: null,

    expoProjectLabel(project = {}) {
      const name = String(project?.name || project?.project_name || project?.expo_project_name || '').trim();
      return name || `Workspace ${project?.id || ''}`.trim();
    },

    expoProjectTargetLabel(project = {}) {
      const branch = String(project?.git_branch || project?.branch || '').trim();
      const platform = String(project?.stack || '').trim();
      const parts = [];
      if (platform) parts.push(platform.toUpperCase());
      if (branch) parts.push(branch);
      return parts.join(' · ');
    },

    expoProjectMatch(project = {}) {
      const stack = String(project?.stack || '').trim().toLowerCase();
      const expoHint = [
        project?.expo_project_id,
        project?.expo_slug,
        project?.eas_project_id,
        project?.eas_slug,
      ].some(value => String(value || '').trim());
      return stack === 'expo' || stack === 'react-native' || expoHint;
    },

    expoProjectSummary(projectId) {
      return this.expoProjectSummaries?.[projectId] || null;
    },

    expoOverviewPrimaryProject() {
      const projects = Array.isArray(this.expoOverview?.projects) ? this.expoOverview.projects : [];
      if (!projects.length) return {};
      const focusedWorkspaceId = String(this.chatProjectId || this.chatProject?.id || '').trim();
      if (focusedWorkspaceId) {
        const focused = projects.find(project => String(project?.workspace_id || project?.id || '').trim() === focusedWorkspaceId);
        if (focused) return focused;
      }
      return projects[0] || {};
    },

    expoProjectBuildList(projectId) {
      return this.expoProjectBuilds?.[projectId] || [];
    },

    expoOverviewLabel() {
      const summary = this.expoOverview?.summary || '';
      if (summary) return summary;
      if (this.expoLoading) return 'Refreshing Expo / EAS status…';
      if (this.expoError) return this.expoError;
      return 'Expo / EAS is idle until Axon loads the workspace link graph.';
    },

    expoStatusTone() {
      const status = String(this.expoOverview?.status || '').trim().toLowerCase();
      if (status === 'healthy' || status === 'ready') return 'border-emerald-500/20 bg-emerald-500/8 text-emerald-200';
      if (status === 'degraded' || status === 'warning') return 'border-amber-500/20 bg-amber-500/8 text-amber-200';
      if (status === 'blocked' || status === 'unavailable') return 'border-rose-500/20 bg-rose-500/8 text-rose-200';
      return 'border-slate-700 bg-slate-950/70 text-slate-300';
    },

    expoStatusChipClass(status) {
      const value = String(status || '').trim().toLowerCase();
      if (value === 'success' || value === 'ready' || value === 'completed') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200';
      if (value === 'queued' || value === 'in_progress' || value === 'running' || value === 'building' || value === 'pending' || value === 'challenge_required') return 'border-amber-500/20 bg-amber-500/10 text-amber-200';
      if (value === 'failed' || value === 'error' || value === 'blocked' || value === 'rejected' || value === 'expired') return 'border-rose-500/20 bg-rose-500/10 text-rose-200';
      return 'border-slate-700 bg-slate-950/70 text-slate-400';
    },

    expoActiveBuilds() {
      const items = Array.isArray(this.expoOverview?.active_builds) ? this.expoOverview.active_builds : [];
      return items.slice(0, 4);
    },

    deliveryItems() {
      const items = Array.isArray(this.deliveryActivity?.items) ? this.deliveryActivity.items : [];
      return items.slice(0, 6);
    },

    deliveryItemLabel(item = {}) {
      const kind = String(item?.kind || '').trim();
      if (kind === 'expo_build') return 'EAS build';
      if (kind === 'vercel_challenge') return 'Vercel approval';
      if (kind === 'vercel_action') return 'Vercel deploy';
      return 'Delivery';
    },

    deliveryItemMeta(item = {}) {
      const parts = [];
      const meta = item?.meta || {};
      if (meta?.platform) parts.push(String(meta.platform).toUpperCase());
      if (meta?.profile) parts.push(String(meta.profile));
      if (meta?.channel) parts.push(String(meta.channel));
      if (meta?.runtime_version) parts.push(String(meta.runtime_version));
      if (item?.created_at) parts.push(this.timeAgo(item.created_at));
      return parts.join(' · ');
    },

    expoBuildStatusLabel(build = {}) {
      const state = String(build?.state || build?.status || '').trim().toLowerCase();
      if (!state) return 'unknown';
      return state.replace(/_/g, ' ');
    },

    expoBuildMeta(build = {}) {
      const parts = [];
      if (build?.platform) parts.push(String(build.platform).toUpperCase());
      if (build?.profile) parts.push(build.profile);
      if (build?.created_at) parts.push(this.timeAgo(build.created_at));
      return parts.join(' · ');
    },

    async loadExpoOverview(force = false) {
      if (this.expoLoading && !force) return;
      this.expoLoading = true;
      this.expoError = '';
      try {
        const qs = force ? '?force_refresh=true' : '';
        const data = await this.api('GET', `/api/devops/expo/overview${qs}`);
        this.expoOverview = {
          ...this.expoOverview,
          ...(data || {}),
          status: data?.status || 'ready',
          summary: data?.summary || data?.message || '',
          updated_at: data?.updated_at || new Date().toISOString(),
          projects: Array.isArray(data?.projects) ? data.projects : [],
          builds: Array.isArray(data?.builds) ? data.builds : [],
          active_builds: Array.isArray(data?.active_builds) ? data.active_builds : [],
        };
      } catch (e) {
        this.expoError = e?.message || 'Expo / EAS status unavailable';
        this.expoOverview = {
          ...this.expoOverview,
          status: 'unavailable',
          summary: this.expoError,
          updated_at: new Date().toISOString(),
        };
      } finally {
        this.expoLoading = false;
      }
    },

    async loadDeliveryActivity(force = false) {
      try {
        const qs = force ? '?force_refresh=true' : '';
        const data = await this.api('GET', `/api/devops/delivery/activity${qs}`);
        this.deliveryActivity = {
          updated_at: data?.updated_at || new Date().toISOString(),
          items: Array.isArray(data?.items) ? data.items : [],
          expo_active_builds: Array.isArray(data?.expo_active_builds) ? data.expo_active_builds : [],
          vercel_pending_actions: Array.isArray(data?.vercel_pending_actions) ? data.vercel_pending_actions : [],
          vercel_recent_actions: Array.isArray(data?.vercel_recent_actions) ? data.vercel_recent_actions : [],
        };
      } catch (e) {
        this.deliveryActivity = {
          updated_at: new Date().toISOString(),
          items: [],
          expo_active_builds: [],
          vercel_pending_actions: [],
          vercel_recent_actions: [],
        };
      }
    },

    async loadExpoProjectSummary(project, force = false) {
      const projectId = Number(project?.id || 0);
      if (!projectId) return null;
      const cached = this.expoProjectSummaries[projectId];
      if (!force && cached?.summary) return cached;
      try {
        const data = await this.api('GET', `/api/devops/expo/projects/${projectId}/status`);
        const summary = {
          project_id: projectId,
          loading: false,
          error: false,
          status: data?.status || 'ready',
          label: data?.label || this.expoProjectLabel(project),
          summary: data?.summary || data?.message || '',
          updated_at: data?.updated_at || new Date().toISOString(),
          expo: data || {},
        };
        this.expoProjectSummaries = { ...this.expoProjectSummaries, [projectId]: summary };
        return summary;
      } catch (e) {
        const summary = {
          project_id: projectId,
          loading: false,
          error: true,
          status: 'unavailable',
          label: this.expoProjectLabel(project),
          summary: e?.message || 'Expo project status unavailable',
          updated_at: new Date().toISOString(),
        };
        this.expoProjectSummaries = { ...this.expoProjectSummaries, [projectId]: summary };
        return summary;
      }
    },

    async loadExpoProjectBuilds(project, force = false) {
      const projectId = Number(project?.id || 0);
      if (!projectId) return [];
      const cached = this.expoProjectBuilds[projectId];
      if (!force && Array.isArray(cached) && cached.length) return cached;
      try {
        const data = await this.api('GET', `/api/devops/expo/projects/${projectId}/builds?limit=5`);
        const builds = Array.isArray(data?.builds) ? data.builds : Array.isArray(data) ? data : [];
        this.expoProjectBuilds = { ...this.expoProjectBuilds, [projectId]: builds };
        return builds;
      } catch (e) {
        this.expoProjectBuilds = { ...this.expoProjectBuilds, [projectId]: [] };
        return [];
      }
    },

    async refreshExpoProject(project, force = false) {
      const projectId = Number(project?.id || 0);
      if (!projectId) return;
      await Promise.all([
        this.loadExpoProjectSummary(project, force),
        this.loadExpoProjectBuilds(project, force),
      ]);
    },

    expoActionPayload(actionType, project, extra = {}) {
      const projectId = Number(project?.id || 0) || null;
      return {
        action_type: actionType,
        workspace_id: projectId,
        project_id: projectId,
        project_name: project?.name || project?.project_name || '',
        platform: extra.platform || '',
        profile: extra.profile || 'development',
        ...extra,
      };
    },

    async requestExpoAction(actionType, project, extra = {}) {
      const payload = this.expoActionPayload(actionType, project, extra);
      this.expoActionLoading = true;
      this.expoLastAction = { action_type: actionType, project_id: payload.project_id, started_at: new Date().toISOString() };
      try {
        let result = await this.api('POST', '/api/devops/expo/actions', payload);
        if (result?.status === 'confirm_required') {
          const confirmed = window.confirm(result?.summary || 'Confirm Expo action?');
          if (!confirmed) {
            this.expoLastAction = {
              ...this.expoLastAction,
              finished_at: new Date().toISOString(),
              status: 'cancelled',
              summary: 'Expo action cancelled',
            };
            return { status: 'cancelled', summary: 'Expo action cancelled' };
          }
          result = await this.api('POST', '/api/devops/expo/actions', { ...payload, confirm: true });
        }
        this.expoLastAction = {
          ...this.expoLastAction,
          finished_at: new Date().toISOString(),
          status: result?.status || 'queued',
          summary: result?.summary || result?.message || 'Expo action sent',
        };
        this.showToast?.(result?.summary || result?.message || 'Expo action sent');
        await this.refreshExpoProject(project, true);
        await this.loadDeliveryActivity?.(true);
        return result;
      } catch (e) {
        this.expoLastAction = {
          ...this.expoLastAction,
          finished_at: new Date().toISOString(),
          status: 'error',
          summary: e?.message || 'Expo action failed',
        };
        this.showToast?.(e?.message || 'Expo action failed');
        throw e;
      } finally {
        this.expoActionLoading = false;
      }
    },

    async requestExpoProjectStatus(project) {
      return this.requestExpoAction('expo.project.status', project, {});
    },

    async requestExpoAndroidDevBuild(project) {
      return this.requestExpoAction('expo.build.android.dev', project, { platform: 'android', profile: 'development' });
    },

    async requestExpoIosDevBuild(project) {
      return this.requestExpoAction('expo.build.ios.dev', project, { platform: 'ios', profile: 'development' });
    },

    async requestExpoBuildList(project) {
      return this.requestExpoAction('expo.build.list', project, { limit: 10 });
    },

    async requestExpoUpdatePublish(project) {
      return this.requestExpoAction('expo.update.publish', project, { platform: 'all', profile: 'production' });
    },
  };
}

window.axonExpoMixin = axonExpoMixin;
