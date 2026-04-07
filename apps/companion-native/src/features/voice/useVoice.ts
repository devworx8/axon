import { useCallback, useState } from 'react';

import { sendVoiceTurn } from '@/api/companion';
import { CompanionConfig, CompanionSession, VoiceTurnResponse } from '@/types/companion';

export function useVoice(
  config: CompanionConfig,
  onSessionUpdate?: (session: CompanionSession) => void,
) {
  const [lastTranscript, setLastTranscript] = useState('');
  const [responseText, setResponseText] = useState('');
  const [lastResult, setLastResult] = useState<VoiceTurnResponse | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitVoiceTurn = useCallback(async (content: string, transcript = content, voiceMode = 'live') => {
    setSending(true);
    setError(null);
    setLastTranscript(transcript);
    setResponseText('');
    setLastResult(null);
    try {
      const result = await sendVoiceTurn(
        {
          session_id: config.sessionId ?? undefined,
          workspace_id: config.workspaceId ?? undefined,
          role: 'user',
          content,
          transcript,
          voice_mode: voiceMode,
        },
        config,
      );
      setResponseText(result.response_text || result.session.summary || '');
      setLastResult(result);
      if (result.session && onSessionUpdate) {
        onSessionUpdate(result.session);
      }
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice request failed');
      throw err;
    } finally {
      setSending(false);
    }
  }, [config, onSessionUpdate]);

  return { lastTranscript, responseText, lastResult, sending, error, submitVoiceTurn };
}
