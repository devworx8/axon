import { useCallback } from 'react';
import type { Dispatch, SetStateAction } from 'react';

import type { CompanionConfig } from '@/types/companion';

type SetConfig = Dispatch<SetStateAction<CompanionConfig>>;
type SetActiveTab = (tab: 'mission' | 'voice' | 'attention' | 'projects' | 'sessions' | 'settings') => void;

export function useWorkspaceActionHandlers({
  setConfig,
  setActiveTab,
  setPreferredWorkspaceId,
  executeAction,
  refreshMission,
  currentSessionId,
}: {
  setConfig: SetConfig;
  setActiveTab: SetActiveTab;
  setPreferredWorkspaceId: (workspaceId: number | null) => void;
  executeAction: (actionType: string, payload?: Record<string, unknown>) => Promise<unknown>;
  refreshMission: (workspaceId?: number | null, sessionId?: number | null) => Promise<unknown>;
  currentSessionId: number | null;
}) {
  const focusWorkspace = useCallback(async (workspaceId: number | null) => {
    setPreferredWorkspaceId(workspaceId);
    setConfig(current => ({ ...current, workspaceId }));
    await executeAction('workspace.focus.set', { workspace_id: workspaceId });
    await refreshMission(workspaceId, currentSessionId);
    setActiveTab('mission');
  }, [currentSessionId, executeAction, refreshMission, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const inspectWorkspace = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('workspace.inspect', { workspace_id: workspaceId });
    setActiveTab('mission');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const restartPreview = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('workspace.preview.restart', { workspace_id: workspaceId });
    setActiveTab('mission');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const stopPreview = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('workspace.preview.stop', { workspace_id: workspaceId });
    setActiveTab('mission');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const deployWorkspace = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('vercel.deploy.promote', { workspace_id: workspaceId });
    setActiveTab('sessions');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const rollbackWorkspace = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('vercel.deploy.rollback', { workspace_id: workspaceId });
    setActiveTab('sessions');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const expoProjectStatus = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('expo.project.status', { workspace_id: workspaceId });
    setActiveTab('mission');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const expoBuildAndroidDev = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('expo.build.android.dev', { workspace_id: workspaceId });
    setActiveTab('sessions');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const expoBuildIosDev = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('expo.build.ios.dev', { workspace_id: workspaceId });
    setActiveTab('sessions');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const expoBuildList = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('expo.build.list', { workspace_id: workspaceId });
    setActiveTab('sessions');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  const expoPublishUpdate = useCallback(async (workspaceId: number | null) => {
    if (workspaceId !== null) {
      setPreferredWorkspaceId(workspaceId);
      setConfig(current => ({ ...current, workspaceId }));
    }
    await executeAction('expo.update.publish', { workspace_id: workspaceId });
    setActiveTab('sessions');
  }, [executeAction, setActiveTab, setConfig, setPreferredWorkspaceId]);

  return {
    focusWorkspace,
    inspectWorkspace,
    restartPreview,
    stopPreview,
    deployWorkspace,
    rollbackWorkspace,
    expoProjectStatus,
    expoBuildAndroidDev,
    expoBuildIosDev,
    expoBuildList,
    expoPublishUpdate,
  };
}
