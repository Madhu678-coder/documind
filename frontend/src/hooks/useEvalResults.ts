import { useEffect, useState } from 'react';
import { getEvalResults } from '../api/eval';
import type { EvalResult } from '../types';

export function useEvalResults(message_id: string | null) {
  const [evalResult, setEvalResult] = useState<EvalResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!message_id) return;

    let cancelled = false;
    setIsLoading(true);
    setError(null);

    getEvalResults(message_id)
      .then((result) => {
        if (!cancelled) setEvalResult(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [message_id]);

  return { evalResult, isLoading, error };
}
