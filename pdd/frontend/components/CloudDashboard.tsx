import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { RemoteCommandStatus, RemoteSessionInfo } from '../api';

type Example = { id: string; metadata: { title?: string; language?: string; isPublic?: boolean } };

async function requestService<T>(token: string, endpoint: string, body?: unknown): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}${endpoint}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(body === undefined ? {} : { 'Idempotency-Key': crypto.randomUUID() }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({})) as { error?: string };
    throw new Error(error.error || `Server returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function CloudDashboard() {
  const [tokenInput, setTokenInput] = useState('');
  const [token, setToken] = useState('');
  const [sessions, setSessions] = useState<RemoteSessionInfo[]>([]);
  const [sessionId, setSessionId] = useState(window.location.pathname.match(/\/connect\/([^/]+)/)?.[1] || '');
  const [examples, setExamples] = useState<Example[]>([]);
  const [command, setCommand] = useState('sync');
  const [args, setArgs] = useState('{"args": []}');
  const [options, setOptions] = useState('{"local": true}');
  const [job, setJob] = useState<RemoteCommandStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    async function refresh() {
      try {
        const [sessionData, exampleData] = await Promise.all([
          requestService<{ sessions: RemoteSessionInfo[] }>(token, 'listSessions'),
          requestService<{ examples: Example[] }>(token, 'listExamples'),
        ]);
        if (!active) return;
        setSessions(sessionData.sessions);
        setExamples(exampleData.examples);
        setSessionId(previous => sessionData.sessions.some(session => session.sessionId === previous)
          ? previous
          : sessionData.sessions.find(session => session.status === 'active')?.sessionId || sessionData.sessions[0]?.sessionId || '');
        setError('');
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [token]);

  useEffect(() => {
    if (!token || !job || ['completed', 'failed', 'cancelled'].includes(job.status)) return;
    let active = true;
    const commandId = job.commandId;
    async function poll() {
      try {
        const data = await requestService<{ command: RemoteCommandStatus }>(token, `getCommandStatus?sessionId=${encodeURIComponent(sessionId)}&commandId=${encodeURIComponent(commandId)}`);
        if (active) setJob(data.command);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [token, job?.commandId, job?.status, sessionId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const payload = { args: JSON.parse(args) as Record<string, unknown>, options: JSON.parse(options) as Record<string, unknown> };
      if (!payload.args || !payload.options || Array.isArray(payload.args) || Array.isArray(payload.options) || typeof payload.args !== 'object' || typeof payload.options !== 'object') {
        throw new Error('Arguments and options must be JSON objects');
      }
      const result = await requestService<{ commandId: string }>(token, 'submitCommand', { sessionId, type: command, payload });
      setJob({ commandId: result.commandId, type: command, status: 'pending', createdAt: new Date().toISOString() });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      await requestService(token, 'cancelCommand', { sessionId, commandId: job.commandId });
      setJob(previous => previous ? { ...previous, status: 'cancelled' } : null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  const selectedSession = sessions.find(session => session.sessionId === sessionId);
  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6 text-surface-100">
      <h1 className="text-2xl font-semibold">PDD self-hosted server</h1>
      <p>Commands run on the connected machine. Model requests use its local credentials or your configured server.</p>
      {!token ? (
        <form onSubmit={event => { event.preventDefault(); setToken(tokenInput.trim()); setTokenInput(''); }} className="space-y-3">
          <label htmlFor="server-token" className="block">Server bearer token</label>
          <input id="server-token" type="password" required autoComplete="off" value={tokenInput} onChange={event => setTokenInput(event.target.value)} className="block w-full p-2 bg-surface-800 rounded border border-surface-600" />
          <button type="submit" className="px-4 py-2 bg-accent-600 rounded">Connect</button>
          <p className="text-sm text-surface-400">The token stays in this page's memory. Reloading clears it.</p>
        </form>
      ) : (
        <>
          <button type="button" onClick={() => { setToken(''); setSessionId(''); setSessions([]); setExamples([]); setJob(null); setError(''); }} className="px-4 py-2 bg-surface-700 rounded">Disconnect</button>
          <form onSubmit={event => { void submit(event); }} className="space-y-3">
            <label htmlFor="session" className="block">Connected machine</label>
            <select id="session" value={sessionId} onChange={event => { setSessionId(event.target.value); setJob(null); }} className="w-full p-2 bg-surface-800 rounded border border-surface-600">
              <option value="">Select a session</option>
              {sessions.map(session => <option key={session.sessionId} value={session.sessionId}>{session.projectName} ({session.status})</option>)}
            </select>
            {sessions.length === 0 && <p>No sessions registered. Run pdd connect with this server's URL and token.</p>}
            <label htmlFor="command" className="block">Command</label>
            <input id="command" required value={command} onChange={event => setCommand(event.target.value)} className="w-full p-2 bg-surface-800 rounded border border-surface-600" />
            <label htmlFor="arguments" className="block">Arguments (JSON)</label>
            <textarea id="arguments" value={args} onChange={event => setArgs(event.target.value)} rows={3} className="w-full p-2 font-mono bg-surface-800 rounded border border-surface-600" />
            <label htmlFor="options" className="block">Options (JSON)</label>
            <textarea id="options" value={options} onChange={event => setOptions(event.target.value)} rows={3} className="w-full p-2 font-mono bg-surface-800 rounded border border-surface-600" />
            <button type="submit" disabled={busy || selectedSession?.status !== 'active'} className="px-4 py-2 bg-accent-600 rounded disabled:opacity-40">Run command</button>
          </form>
          {job && <section aria-label="Command result" className="space-y-2">
            <h2 className="font-semibold">{job.type}: {job.status}</h2>
            {['pending', 'processing'].includes(job.status) && <button type="button" onClick={() => { void cancel(); }} className="px-4 py-2 bg-surface-700 rounded">Cancel command</button>}
            <pre className="p-3 bg-surface-900 rounded whitespace-pre-wrap break-words">{JSON.stringify(job.response ?? {}, null, 2)}</pre>
          </section>}
          <section aria-label="Example library">
            <h2 className="font-semibold mb-2">Example library</h2>
            <ul className="space-y-1">{examples.map(example => <li key={example.id}>{example.metadata.title || example.id} {example.metadata.language && `(${example.metadata.language})`}</li>)}</ul>
            {examples.length === 0 && <p>No examples stored. Upload examples explicitly through submitExample.</p>}
          </section>
        </>
      )}
      {error && <p role="alert" className="text-red-400">{error}</p>}
    </main>
  );
}
