import { useCallback, useState } from 'react';

import {
  confirmRiskChallenge,
  createMobileElevation,
  executeMobileAction,
  fetchActionReceipts,
  fetchControlCapabilities,
  fetchMobileTrust,
  fetchRiskChallenges,
  rejectRiskChallenge,
} from '@/api/control';
import { fetchMcpServers, fetchMcpSessions } from '@/api/mcp';
import {
  ActionReceipt,
  CompanionConfig,
  ControlCapability,
  McpServerSpec,
  McpSessionState,
  RiskChallenge,
  RiskTier,
  TrustSnapshot,
  TypedActionRequest,
  TypedActionResult,
} from '@/types/companion';
import { verifyLocalBiometric } from '@/lib/localBiometric';

const RISK_ORDER: Record<string, number> = {
  observe: 0,
  act: 1,
  destructive: 2,
  break_glass: 3,
};

function riskAtLeast(current?: string, target?: string) {
  return (RISK_ORDER[String(current || 'observe')] ?? 0) >= (RISK_ORDER[String(target || 'observe')] ?? 0);
}

async function verifyLocally(riskTier: string) {
  return verifyLocalBiometric(`Unlock Axon Online for ${riskTier.replace('_', ' ')} control`);
}

export function useMobileControl(config: CompanionConfig) {
  const [trust, setTrust] = useState<TrustSnapshot | null>(null);
  const [capabilities, setCapabilities] = useState<ControlCapability[]>([]);
  const [receipts, setReceipts] = useState<ActionReceipt[]>([]);
  const [challenges, setChallenges] = useState<RiskChallenge[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServerSpec[]>([]);
  const [mcpSessions, setMcpSessions] = useState<McpSessionState[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [actingActionType, setActingActionType] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<TypedActionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const [trustResult, capabilityResult, receiptResult, challengeResult, mcpServerResult, mcpSessionResult] = await Promise.all([
        fetchMobileTrust(config),
        fetchControlCapabilities(config),
        fetchActionReceipts(config, 20),
        fetchRiskChallenges(config, 'pending', 20),
        fetchMcpServers(config),
        fetchMcpSessions(config),
      ]);
      setTrust(trustResult.trust || null);
      setCapabilities(capabilityResult.capabilities || []);
      setReceipts(receiptResult.receipts || []);
      setChallenges(challengeResult.challenges || []);
      setMcpServers(mcpServerResult.servers || []);
      setMcpSessions(mcpSessionResult.sessions || []);
      return {
        trust: trustResult.trust || null,
        capabilities: capabilityResult.capabilities || [],
        receipts: receiptResult.receipts || [],
        challenges: challengeResult.challenges || [],
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to refresh mobile control state');
      throw err;
    } finally {
      setRefreshing(false);
    }
  }, [config]);

  const elevateTo = useCallback(async (
    targetRiskTier: RiskTier = 'destructive',
    ttlMinutes = 15,
  ) => {
    setActingActionType(`elevate:${targetRiskTier}`);
    setError(null);
    try {
      const verifiedVia = await verifyLocally(targetRiskTier);
      const result = await createMobileElevation(
        {
          target_risk_tier: targetRiskTier,
          verified_via: verifiedVia,
          ttl_minutes: ttlMinutes,
        },
        config,
      );
      setTrust(result.trust || null);
      await refresh();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not elevate this device');
      throw err;
    } finally {
      setActingActionType(null);
    }
  }, [config, refresh]);

  const executeAction = useCallback(async (request: TypedActionRequest) => {
    setActingActionType(request.action_type);
    setError(null);
    try {
      const result = await executeMobileAction(request, config);
      setLastAction(result);
      await refresh();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed');
      throw err;
    } finally {
      setActingActionType(null);
    }
  }, [config, refresh]);

  const confirmChallenge = useCallback(async (challenge: RiskChallenge) => {
    const targetRiskTier = String(challenge.risk_tier || 'destructive') as RiskTier;
    if (!trust || !riskAtLeast(String(trust.effective_max_risk_tier || 'observe'), targetRiskTier)) {
      await elevateTo(targetRiskTier);
    }
    setActingActionType(`confirm:${challenge.action_type}`);
    setError(null);
    try {
      const result = await confirmRiskChallenge(challenge.id, config);
      setLastAction(result.result || null);
      await refresh();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Challenge confirmation failed');
      throw err;
    } finally {
      setActingActionType(null);
    }
  }, [config, elevateTo, refresh, trust]);

  const rejectChallenge = useCallback(async (challengeId: number) => {
    setActingActionType(`reject:${challengeId}`);
    setError(null);
    try {
      const result = await rejectRiskChallenge(challengeId, config);
      await refresh();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Challenge rejection failed');
      throw err;
    } finally {
      setActingActionType(null);
    }
  }, [config, refresh]);

  return {
    trust,
    capabilities,
    receipts,
    challenges,
    mcpServers,
    mcpSessions,
    refreshing,
    actingActionType,
    lastAction,
    error,
    refresh,
    elevateTo,
    executeAction,
    confirmChallenge,
    rejectChallenge,
    setLastAction,
  };
}
