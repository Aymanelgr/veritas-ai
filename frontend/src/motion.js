import { useEffect, useRef, useState } from "react";

// People can ask their OS for less animation; we respect that everywhere.
export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Animate a number from its previous value to `value` (stat cards).
export function useCountUp(value, duration = 700) {
  const [shown, setShown] = useState(reducedMotion() ? value : 0);
  const from = useRef(shown);

  useEffect(() => {
    if (reducedMotion()) {
      setShown(value);
      return undefined;
    }
    const start = performance.now();
    const begin = from.current;
    let frame;
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - (1 - t) ** 3; // ease-out: fast start, gentle stop
      setShown(Math.round(begin + (value - begin) * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return shown;
}

// Reveal a list of tokens one by one (answers appear word by word).
export function useReveal(count, perToken = 28) {
  const [shown, setShown] = useState(reducedMotion() ? count : 0);
  useEffect(() => {
    if (reducedMotion() || shown >= count) return undefined;
    const timer = setTimeout(() => setShown((n) => Math.min(n + 1, count)), perToken);
    return () => clearTimeout(timer);
  }, [shown, count, perToken]);
  return shown;
}
