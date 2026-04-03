import { useCallback, useState } from 'react';

export function useAsyncState<T>(initial: T) {
  const [value, setValue] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (task: () => Promise<T>) => {
    setLoading(true);
    setError(null);
    try {
      const next = await task();
      setValue(next);
      return next;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { value, setValue, loading, error, run };
}

