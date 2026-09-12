import path from 'node:path';
import { defineConfig, loadConfigFromFile, mergeConfig } from '/srv/platform-dev/repos/platform-web/node_modules/vite/dist/node/index.js';

// Keep each application's canonical plugins, federation and API proxy rules.
export default defineConfig(async (env) => {
  const root = process.cwd();
  if (!root.startsWith('/srv/platform-dev/repos/platform-web/apps/mfe-')) {
    throw new Error('Unexpected DEV application directory');
  }
  const loaded = await loadConfigFromFile(env, path.join(root, 'vite.config.ts'));
  if (!loaded) throw new Error('Canonical Vite configuration unavailable');
  const app = path.basename(root);
  const base = app === 'mfe-shell' ? '/' : `/mfe/${app.slice(4)}/`;
  const config = mergeConfig(loaded.config, {
    base,
    plugins: [{
      name: 'devai-legacy-federation-health-path',
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (base !== '/' && request.url === '/remoteEntry.js') {
            response.writeHead(302, { Location: base + 'remoteEntry.js' });
            response.end();
            return;
          }
          next();
        });
      },
    }],
    server: {
      host: '127.0.0.1',
      strictPort: true,
      allowedHosts: ['devai.acik.com'],
      origin: 'https://devai.acik.com',
      cors: { origin: 'https://devai.acik.com' },
      hmr: { protocol: 'wss', host: 'devai.acik.com', clientPort: 443 },
    },
  });
  // Several legacy MFE configs advertise wildcard CORS in custom headers.
  delete config.server.headers?.['Access-Control-Allow-Origin'];
  return config;
});
