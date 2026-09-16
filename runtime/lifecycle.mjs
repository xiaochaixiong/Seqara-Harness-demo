// Preload for the official CLI. EOF also tears down the child if the desktop exits.
import './native-command-loader.mjs';
import network from '../desktop/network-guard.cjs';
network.install();
import { createInterface } from 'node:readline';
if (process.env.NV_HARNESS_MANAGED === '1') {
  const input = createInterface({ input: process.stdin });
  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    process.emit('SIGTERM');
    const deadline = setTimeout(() => process.exit(0), 12000);
    deadline.unref();
  };
  input.on('line', line => { if (line === 'shutdown') stop(); });
  input.on('close', stop);
}
