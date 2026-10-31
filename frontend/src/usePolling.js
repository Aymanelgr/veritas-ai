import { useCallback, useEffect, useState } from "react";

// Load data now, and again every `interval` ms while `shouldPoll(data)` is true.
// Used to watch documents while the background worker processes them.
export default function usePolling(loader, shouldPoll = () => false, interval = 3000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const reload = useCallback(
    () => loader().then(setData, setError),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loader],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (data === null || !shouldPoll(data)) return undefined;
    const timer = setInterval(reload, interval);
    return () => clearInterval(timer);
  }, [data, shouldPoll, reload, interval]);

  return { data, error, reload };
}

export const isBusy = (status) => status === "uploaded" || status === "processing";
