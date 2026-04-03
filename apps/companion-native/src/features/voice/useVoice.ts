import { useCallback, useState } from 'react';

import { sendVoiceTurn } from '@/api/companion';
import { CompanionConfig, CompanionSession } from '@/types/companion';

export function useVoice(
  config: CompanionConfig,
  onSessionUpdate?: (session: CompanionSession) => void,
) {
  const [lastTranscript, setLastTranscript] = useState('');
  const [responseText, setResponseText] = useState('');
  const [sending, setSending] = useState(false);

  const submitVoiceTurn = useCallback(async (content: string, transcript = content) => {
    setSending(true);
    try {
      const result = await sendVoiceTurn(
        {
          session_id: config.sessionId ?? undefined,
          workspace_id: config.workspaceId ?? undefined,
          role: 'user',
          content,
          transcript,
        },
        config,
      );
      setLastTranscript(transcript);
      setResponseText(result.response_text || result.session.summary || '');
      if (result.session && onSessionUpdate) {
        onSessionUpdate(result.session);
      }
      return result;
    } finally {
      setSending(false);
    }
  }, [config, onSessionUpdate]);

  return { lastTranscript, responseText, sending, submitVoiceTurn };
}
