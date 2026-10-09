import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

interface ReauthModalProps {
  onClose: () => void;
}

export function ReauthModal({ onClose }: ReauthModalProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [server, setServer] = useState('');
  const [message, setMessage] = useState('Checking connection settings...');

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    api.getCloudConfiguration().then(config => {
      setServer(config.cloud_url);
      setMessage(config.cloud_enabled ? 'Server URL and bearer token are configured.' : 'Set PDD_CLOUD_URL and PDD_CLOUD_TOKEN or PDD_CLOUD_TOKEN_FILE, then restart pdd connect.');
    }).catch(() => setMessage('Could not read connection settings.'));
    return () => element?.close();
  }, []);

  return (
    <dialog ref={dialog} onCancel={onClose} onClose={onClose} className="max-w-lg p-6 bg-surface-900 text-surface-100 rounded-xl border border-surface-600 backdrop:bg-black/60">
      <h2 className="text-lg font-semibold mb-3">Self-hosted server connection</h2>
      {server && <p className="mb-3 break-all">{server}</p>}
      <p className="mb-4">{message}</p>
      <button type="button" onClick={onClose} className="px-4 py-2 rounded bg-surface-700">Close</button>
    </dialog>
  );
}
