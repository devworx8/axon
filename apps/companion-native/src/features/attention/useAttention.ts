import { useCallback, useState } from 'react';

import { fetchAttentionInbox, fetchAttentionSummary, updateAttentionItemState } from '@/api/attention';
import { CompanionConfig, AttentionItem } from '@/types/companion';

export function useAttention(config: CompanionConfig) {
  const [summary, setSummary] = useState<{ counts: Record<string, number>; top_now: AttentionItem[]; top_waiting_on_me: AttentionItem[]; top_watch: AttentionItem[] }>({
    counts: { now: 0, waiting_on_me: 0, watch: 0 },
    top_now: [],
    top_waiting_on_me: [],
    top_watch: [],
  });
  const [inbox, setInbox] = useState<{ now: AttentionItem[]; waiting_on_me: AttentionItem[]; watch: AttentionItem[] }>({
    now: [],
    waiting_on_me: [],
    watch: [],
  });

  const refresh = useCallback(async () => {
    const [nextSummary, nextInbox] = await Promise.all([
      fetchAttentionSummary(config),
      fetchAttentionInbox(config),
    ]);
    setSummary(nextSummary);
    setInbox(nextInbox);
    return { summary: nextSummary, inbox: nextInbox };
  }, [config]);

  const resolveItem = useCallback(async (itemId: number, note = '') => {
    await updateAttentionItemState(itemId, 'resolve', { resolution_note: note }, config);
    return refresh();
  }, [config, refresh]);

  return { summary, inbox, refresh, resolveItem };
}

