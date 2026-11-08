import { describe, expect, it } from 'vitest';
import { ApiError, isMissingEndpoint } from './client';

describe('isMissingEndpoint', () => {
  it('recognises FastAPI\'s answer for a route the server does not have', () => {
    expect(isMissingEndpoint(new ApiError('http', 'Not Found', 404))).toBe(true);
  });
  it('does not mistake an unknown proposal, a server error or a network failure for an old server', () => {
    expect(isMissingEndpoint(new ApiError('http', "Proposal '0xabc' not found.", 404))).toBe(false);
    expect(isMissingEndpoint(new ApiError('http', 'Not Found', 500))).toBe(false);
    expect(isMissingEndpoint(new ApiError('network', 'Cannot reach the API'))).toBe(false);
    expect(isMissingEndpoint(new Error('Not Found'))).toBe(false);
  });
});
