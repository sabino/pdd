import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CloudDashboard } from '../components/CloudDashboard';

afterEach(() => { vi.unstubAllGlobals(); });

function mockService() {
  const fetchMock = vi.fn(async (url: string, options: RequestInit) => {
    const token = (options.headers as Record<string, string>).Authorization;
    if (token !== 'Bearer valid-token') return new Response(JSON.stringify({ error: 'Invalid bearer token' }), { status: 401 });
    if (url.endsWith('listSessions')) return new Response(JSON.stringify({ sessions: [{ sessionId: 'session-1', projectName: 'demo', status: 'active' }] }));
    if (url.endsWith('listExamples')) return new Response(JSON.stringify({ examples: [] }));
    if (url.endsWith('submitCommand')) return new Response(JSON.stringify({ commandId: 'command-1', status: 'pending' }));
    throw new Error(`Unexpected endpoint: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('Self-hosted dashboard', () => {
  it('waits for a token before contacting the service', () => {
    const fetchMock = mockService();
    render(<CloudDashboard />);
    expect(screen.getByLabelText('Server bearer token')).toHaveAttribute('type', 'password');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('lists sessions and sends the existing command contract', async () => {
    const fetchMock = mockService();
    render(<CloudDashboard />);
    fireEvent.change(screen.getByLabelText('Server bearer token'), { target: { value: 'valid-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await screen.findByRole('option', { name: 'demo (active)' });
    fireEvent.change(screen.getByLabelText('Arguments (JSON)'), { target: { value: '{"args":["--help"]}' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run command' }));
    await screen.findByText('sync: pending');
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith('submitCommand'));
    expect(JSON.parse(String(call?.[1].body))).toEqual({ sessionId: 'session-1', type: 'sync', payload: { args: { args: ['--help'] }, options: { local: true } } });
    expect((call?.[1].headers as Record<string, string>)['Idempotency-Key']).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(screen.getByLabelText('Server bearer token')).toHaveValue('');
  });

  it('shows an authentication failure without a separate OAuth flow', async () => {
    mockService();
    render(<CloudDashboard />);
    fireEvent.change(screen.getByLabelText('Server bearer token'), { target: { value: 'wrong-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Invalid bearer token'));
  });
});
