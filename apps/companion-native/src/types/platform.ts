import type {
  CompanionLiveSnapshot,
  CompanionSession,
  CompanionVoiceTurn,
  RiskTier,
  TrustSnapshot,
} from './companion-core';
import type {
  ActionReceipt,
  AttentionItem,
  ControlCapability,
  McpServerSpec,
  McpSessionState,
  RiskChallenge,
  WorkspaceRelationship,
} from './workflow';
import type { AxonModeStatus } from './axon';

export type WorkspaceSummary = {
  workspace?: Record<string, unknown>;
  relationships?: WorkspaceRelationship[];
  attention?: unknown;
  expo?: ExpoProjectStatus | null;
};

export type PlatformSystemStatus = {
  key: string;
  label: string;
  status: string;
  linked?: boolean;
  urgent?: boolean;
  summary?: string;
  meta?: Record<string, unknown>;
};

export type PlatformProjectCard = {
  workspace: {
    id?: number | null;
    name?: string;
    path?: string;
    git_branch?: string;
    status?: string;
  };
  preview?: {
    url?: string;
    status?: string;
    healthy?: boolean;
    running?: boolean;
    last_error?: string;
  } | null;
  relationships?: WorkspaceRelationship[];
  attention?: {
    counts?: Record<string, number>;
    top_now?: AttentionItem[];
    top_waiting_on_me?: AttentionItem[];
    top_watch?: AttentionItem[];
  };
  expo?: ExpoProjectStatus | null;
};

export type PlatformSnapshot = {
  at?: string;
  posture?: 'healthy' | 'degraded' | 'urgent' | string;
  focus?: {
    workspace_id?: number | null;
    session_id?: number | null;
    workspace?: {
      id?: number | null;
      name?: string;
      path?: string;
      git_branch?: string;
      status?: string;
    };
    preview?: {
      url?: string;
      status?: string;
      healthy?: boolean;
      running?: boolean;
      last_error?: string;
    } | null;
    relationships?: WorkspaceRelationship[];
  };
  axon?: AxonModeStatus;
  live?: CompanionLiveSnapshot;
  attention?: {
    summary?: {
      counts?: Record<string, number>;
      top_now?: AttentionItem[];
      top_waiting_on_me?: AttentionItem[];
      top_watch?: AttentionItem[];
    };
    inbox?: {
      now?: AttentionItem[];
      waiting_on_me?: AttentionItem[];
      watch?: AttentionItem[];
      counts?: Record<string, number>;
    };
  };
  systems?: PlatformSystemStatus[];
  trust?: TrustSnapshot;
  quick_actions?: Array<{
    action_type: string;
    label?: string;
    risk_tier?: RiskTier | string;
    available?: boolean;
    planned?: boolean;
    quick_action?: string;
  }>;
  sessions?: CompanionSession[];
  latest_command_outcome?: ActionReceipt | null;
  latest_voice_outcome?: CompanionVoiceTurn | null;
  next_required_action?: RiskChallenge | AttentionItem | null;
  projects?: PlatformProjectCard[];
  mcp?: {
    server_count?: number;
    session_count?: number;
    servers?: McpServerSpec[];
    sessions?: McpSessionState[];
  };
  expo?: {
    project_count?: number;
    build_count?: number;
    last_sync_at?: string;
    projects?: ExpoProjectStatus[];
  };
};

export type ExpoBuildEntry = {
  id?: string;
  name?: string;
  platform?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  branch?: string;
  message?: string;
  actor?: string;
  url?: string;
  runtime_version?: string;
  commit_sha?: string;
  artifact_url?: string;
  developer_tool?: string;
  meta?: Record<string, unknown>;
};

export type ExpoProjectStatus = {
  project_id?: string;
  project_name?: string;
  account_name?: string;
  owner?: string;
  team_name?: string;
  slug?: string;
  runtime?: string;
  runtime_version?: string;
  status?: string;
  build_profile?: string;
  branch?: string;
  platform?: string;
  update_channel?: string;
  last_build_status?: string;
  last_build_at?: string;
  last_update_at?: string;
  latest_builds?: ExpoBuildEntry[];
  active_builds?: ExpoBuildEntry[];
  latest_updates?: ExpoBuildEntry[];
  available_actions?: string[];
  meta?: Record<string, unknown>;
};
