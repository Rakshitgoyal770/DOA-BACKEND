/**
 * Presentation-only metadata for DAOs: ticker, brand colour, and the chain name for
 * Snapshot's numeric network id. This is styling, not data: every number on screen
 * comes from the API. A DAO the backend adds later still renders (neutral fallback).
 */
export interface DaoMeta {
  symbol: string;
  color: string;
  /** key understood by the hero sculpture's hover effect */
  hoverKey: string | null;
}

const META: Record<string, DaoMeta> = {
  'arbitrumfoundation.eth': { symbol: 'ARB', color: '#28A0F0', hoverKey: 'arbitrum' },
  'aavedao.eth': { symbol: 'AAVE', color: '#B6509E', hoverKey: 'aave' },
  'opcollective.eth': { symbol: 'OP', color: '#FF0420', hoverKey: 'optimism' },
  'uniswapgovernance.eth': { symbol: 'UNI', color: '#FF007A', hoverKey: 'uniswap' },
  'ens.eth': { symbol: 'ENS', color: '#5298FF', hoverKey: 'ens' },
};

export function daoMeta(spaceId: string, name?: string): DaoMeta {
  return (
    META[spaceId] ?? {
      symbol: (name ?? spaceId).replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase() || 'DAO',
      color: '#5C5852',
      hoverKey: null,
    }
  );
}

const CHAINS: Record<string, string> = {
  '1': 'Ethereum',
  '10': 'OP Mainnet',
  '137': 'Polygon',
  '8453': 'Base',
  '42161': 'Arbitrum One',
};

export function chainName(network: string | null | undefined): string {
  if (!network) return '—';
  return CHAINS[network] ?? `Chain ${network}`;
}
