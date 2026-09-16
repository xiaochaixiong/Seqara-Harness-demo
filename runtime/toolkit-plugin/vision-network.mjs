import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=process.env.NV_DESKTOP_ROOT||fileURLToPath(new URL('../../',import.meta.url));
createRequire(import.meta.url)(path.join(root,'desktop/network-guard.cjs')).install();
