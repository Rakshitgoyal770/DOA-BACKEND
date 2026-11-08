import React, { useEffect, useState } from 'react';
import { WifiOff } from 'lucide-react';
import { api } from '../../api/endpoints';
import { API_BASE_URL } from '../../config';
import { Button } from '../ui/Button';

/**
 * Pings GET / on load. If the backend is down, shows a banner and keeps retrying
 * every 15 seconds so the page recovers on its own once the API is started.
 */
export const ConnectionBanner: React.FC<{ onRecovered: () => void }> = ({ onRecovered }) => {
  const [down, setDown] = useState(false);
  const [checking, setChecking] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const check = async () => {
      setChecking(true);
      try {
        await api.health({ signal: controller.signal });
        if (cancelled) return;
        setDown((wasDown) => {
          if (wasDown) onRecovered();
          return false;
        });
      } catch {
        if (cancelled) return;
        setDown(true);
        timer = setTimeout(check, 15_000);
      } finally {
        if (!cancelled) setChecking(false);
      }
    };
    void check();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
    // onRecovered is stable (useCallback in App)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  if (!down) return null;
  return (
    <div role="alert" className="bg-[#FCEEEA] border-b border-[#F2C5BC] text-[#8E2F20]">
      <div className="quorum-container py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <WifiOff size={16} aria-hidden />
        <span className="flex-1 min-w-0">
          The data service at <code className="font-mono text-xs">{API_BASE_URL}</code> is not responding. Retrying automatically.
        </span>
        <Button size="sm" variant="secondary" loading={checking} onClick={() => setAttempt((a) => a + 1)}>
          Retry now
        </Button>
      </div>
    </div>
  );
};
