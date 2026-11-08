import React, { createContext, useContext, useMemo } from 'react';
import { api } from '../api/endpoints';
import type { DaoSummary } from '../api/types';
import { useAsync } from '../hooks/useAsync';

interface DaosContextValue {
  daos: DaoSummary[] | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
  /** space id -> display name, for labelling proposals */
  nameOf: (spaceId: string) => string;
}

const DaosContext = createContext<DaosContextValue | null>(null);

/** Loads GET /daos once for the whole app (nav, filters, search and the home page all need it). */
export const DaosProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const state = useAsync((signal) => api.listDaos({ signal }), []);
  const value = useMemo<DaosContextValue>(() => {
    const names = new Map((state.data ?? []).map((d) => [d.id, d.name]));
    return {
      daos: state.data,
      error: state.error,
      loading: state.loading,
      reload: state.reload,
      nameOf: (id) => names.get(id) ?? id,
    };
  }, [state.data, state.error, state.loading, state.reload]);
  return <DaosContext.Provider value={value}>{children}</DaosContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components
export function useDaos(): DaosContextValue {
  const ctx = useContext(DaosContext);
  if (!ctx) throw new Error('useDaos must be used inside <DaosProvider>');
  return ctx;
}
