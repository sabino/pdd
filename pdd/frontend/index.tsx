
import React from 'react';
import './styles.css';
import ReactDOM from 'react-dom/client';
import App from './App';
import { CloudDashboard } from './components/CloudDashboard';
import { ToastProvider } from './components/Toast';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

const root = ReactDOM.createRoot(rootElement);
root.render(
  <React.StrictMode>
    <ToastProvider>
      {/^\/(cloud|connect\/)/.test(window.location.pathname) ? <CloudDashboard /> : <App />}
    </ToastProvider>
  </React.StrictMode>
);
