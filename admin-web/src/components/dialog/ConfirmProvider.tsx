import { createContext, type PropsWithChildren, useCallback, useContext, useRef, useState } from "react";

type ConfirmOptions = {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

type PromptOptions = {
  title: string;
  message?: string;
  label?: string;
  defaultValue?: string;
  placeholder?: string;
  required?: boolean;
  confirmLabel?: string;
};

type DialogRequest =
  | ({ kind: "confirm" } & ConfirmOptions)
  | ({ kind: "prompt" } & PromptOptions);

type ConfirmContextValue = {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  promptText: (options: PromptOptions) => Promise<string | null>;
};

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function ConfirmProvider({ children }: PropsWithChildren) {
  const [request, setRequest] = useState<DialogRequest | null>(null);
  const [inputValue, setInputValue] = useState("");
  const resolver = useRef<(value: boolean | string | null) => void>();

  const close = useCallback((value: boolean | string | null) => {
    resolver.current?.(value);
    resolver.current = undefined;
    setRequest(null);
  }, []);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve as (value: boolean | string | null) => void;
      setRequest({ kind: "confirm", ...options });
    });
  }, []);

  const promptText = useCallback((options: PromptOptions) => {
    return new Promise<string | null>((resolve) => {
      resolver.current = resolve as (value: boolean | string | null) => void;
      setInputValue(options.defaultValue ?? "");
      setRequest({ kind: "prompt", ...options });
    });
  }, []);

  function handlePromptSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (request?.kind === "prompt" && request.required && !inputValue.trim()) return;
    close(inputValue);
  }

  return (
    <ConfirmContext.Provider value={{ confirm, promptText }}>
      {children}
      {request && (
        <div className="dialog-overlay" onMouseDown={(e) => e.target === e.currentTarget && close(request.kind === "confirm" ? false : null)}>
          {request.kind === "confirm" ? (
            <div className="dialog-card" role="alertdialog" aria-modal="true">
              <h3>{request.title}</h3>
              {request.message && <p>{request.message}</p>}
              <div className="dialog-actions">
                <button className="btn-secondary" onClick={() => close(false)}>
                  {request.cancelLabel ?? "Cancel"}
                </button>
                <button
                  className={request.danger ? "btn-danger" : "btn-secondary"}
                  onClick={() => close(true)}
                  autoFocus
                >
                  {request.confirmLabel ?? "Confirm"}
                </button>
              </div>
            </div>
          ) : (
            <form className="dialog-card" role="dialog" aria-modal="true" onSubmit={handlePromptSubmit}>
              <h3>{request.title}</h3>
              {request.message && <p>{request.message}</p>}
              <div className="field">
                {request.label && <label>{request.label}</label>}
                <input
                  autoFocus
                  value={inputValue}
                  placeholder={request.placeholder}
                  onChange={(e) => setInputValue(e.target.value)}
                />
              </div>
              <div className="dialog-actions">
                <button type="button" className="btn-secondary" onClick={() => close(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn-secondary" disabled={request.required && !inputValue.trim()}>
                  {request.confirmLabel ?? "Submit"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmContextValue {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within a ConfirmProvider");
  return ctx;
}
