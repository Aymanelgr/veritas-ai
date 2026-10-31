import { createContext, useCallback, useContext, useState } from "react";

// Small pop-up messages in the corner. Any component can call useToast()("Saved").
const ToastContext = createContext(() => {});
const DURATION = 5000;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const remove = useCallback((id) => {
    // Play the exit animation first, then remove the toast.
    setToasts((all) => all.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 250);
  }, []);

  const push = useCallback((message, { tone = "info", action } = {}) => {
    const id = crypto.randomUUID();
    setToasts((all) => [...all.slice(-3), { id, message, tone, action }]);
    setTimeout(() => remove(id), DURATION);
  }, [remove]);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone} ${t.leaving ? "leaving" : ""}`}>
            <span>{t.message}</span>
            {t.action && (
              <button className="link" onClick={() => { t.action.onClick(); remove(t.id); }}>
                {t.action.label}
              </button>
            )}
            <button className="toast-close" aria-label="Close" onClick={() => remove(t.id)}>×</button>
            <span className="toast-timer" style={{ animationDuration: `${DURATION}ms` }} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
