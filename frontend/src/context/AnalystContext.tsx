import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { AnalystScope } from '../lib/analystScope';

interface AnalystContextValue {
  isOpen: boolean;
  /** what the analyst can be focused on (proposal and/or DAO); null = only "all DAOs" */
  scope: AnalystScope | null;
  /**
   * Open the analyst. With no argument it uses the page the user is on (a proposal
   * page offers proposal + its DAO, a DAO page offers the DAO); pass `null` to open it unfocused.
   */
  open: (scope?: AnalystScope | null) => void;
  close: () => void;
  /** Called by a page to say what the user is looking at (cleared on unmount). */
  setPageScope: (scope: AnalystScope | null) => void;
}

const AnalystContext = createContext<AnalystContextValue | null>(null);

export const AnalystProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isOpen, setOpen] = useState(false);
  const [scope, setScope] = useState<AnalystScope | null>(null);
  const pageScopeRef = useRef<AnalystScope | null>(null);

  const open = useCallback((next?: AnalystScope | null) => {
    setScope(next === undefined ? pageScopeRef.current : next);
    setOpen(true);
  }, []);
  const close = useCallback(() => setOpen(false), []);
  const setPageScope = useCallback((next: AnalystScope | null) => {
    pageScopeRef.current = next;
  }, []);

  const value = useMemo(() => ({ isOpen, scope, open, close, setPageScope }), [isOpen, scope, open, close, setPageScope]);
  return <AnalystContext.Provider value={value}>{children}</AnalystContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components
export function useAnalyst(): AnalystContextValue {
  const ctx = useContext(AnalystContext);
  if (!ctx) throw new Error('useAnalyst must be used inside <AnalystProvider>');
  return ctx;
}

/** Register what is on screen as the analyst's default focus while the calling page is mounted. */
// eslint-disable-next-line react-refresh/only-export-components
export function useAnalystPageScope(scope: AnalystScope | null): void {
  const { setPageScope } = useAnalyst();
  const proposalId = scope?.proposal?.id;
  const proposalTitle = scope?.proposal?.title;
  const daoId = scope?.dao?.id;
  const daoName = scope?.dao?.name;
  useEffect(() => {
    const next: AnalystScope = {};
    if (proposalId) next.proposal = { id: proposalId, title: proposalTitle ?? '' };
    if (daoId) next.dao = { id: daoId, name: daoName ?? daoId };
    setPageScope(next.proposal || next.dao ? next : null);
    return () => setPageScope(null);
  }, [proposalId, proposalTitle, daoId, daoName, setPageScope]);
}
