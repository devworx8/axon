import { axonRequest } from './client';
import { AttentionItem, CompanionConfig } from '@/types/companion';

export async function fetchAttentionSummary(config?: CompanionConfig) {
  return axonRequest<{ counts: Record<string, number>; top_now: AttentionItem[]; top_waiting_on_me: AttentionItem[]; top_watch: AttentionItem[] }>(
    '/api/attention/summary?limit=10',
    {},
    config,
  );
}

export async function fetchAttentionInbox(config?: CompanionConfig) {
  return axonRequest<{ counts: Record<string, number>; now: AttentionItem[]; waiting_on_me: AttentionItem[]; watch: AttentionItem[] }>(
    '/api/attention/inbox?limit=50',
    {},
    config,
  );
}

export async function updateAttentionItemState(
  itemId: number,
  action: 'ack' | 'resolve' | 'snooze' | 'assign',
  body: Record<string, unknown> = {},
  config?: CompanionConfig,
) {
  const path = `/api/attention/items/${itemId}/${action}`;
  return axonRequest<AttentionItem>(path, { method: 'POST', body: JSON.stringify(body) }, config);
}

