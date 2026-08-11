import { defineConfig, searchForWorkspaceRoot } from 'vite';

export default defineConfig({
  publicDir: '../model',
  server: { fs: { allow: [searchForWorkspaceRoot(process.cwd()), '..'] } },
  build: { chunkSizeWarningLimit: 850 },
});
