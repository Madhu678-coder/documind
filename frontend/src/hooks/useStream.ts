import { useEffect, useRef, useState } from 'react';

interface UseStreamOptions {
  onMessage?: (event: MessageEvent) => void;
  onError?: (event: Event) => void;
  onOpen?: (event: Event) => void;
  token?: string;
}

export function useStream(url: string | null, options: UseStreamOptions = {}) {
  const [isConnected, setIsConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const close = () => {
    esRef.current?.close();
    esRef.current = null;
    setIsConnected(false);
  };

  useEffect(() => {
    if (!url) return;

    const fullUrl = optionsRef.current.token
      ? `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(optionsRef.current.token)}`
      : url;

    const es = new EventSource(fullUrl);
    esRef.current = es;

    es.onopen = (e) => {
      setIsConnected(true);
      optionsRef.current.onOpen?.(e);
    };

    es.onmessage = (e) => {
      optionsRef.current.onMessage?.(e);
    };

    es.onerror = (e) => {
      setIsConnected(false);
      optionsRef.current.onError?.(e);
    };

    return () => {
      es.close();
      esRef.current = null;
      setIsConnected(false);
    };
  }, [url]);

  return { isConnected, close };
}
