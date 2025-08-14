import { defineConfig } from 'vite'
import path from 'node:path'
import electron from 'vite-plugin-electron/simple'

const isRunningOnBrowser = process.env.BUILD_TARGET === 'web'


// https://vitejs.dev/config/
export default defineConfig({
  root: path.join(__dirname, 'src/renderer'), // 👈 set renderer root folder
  build: {
    rollupOptions: {
      input: {
        index: path.join(__dirname, 'src/renderer/index.html'), // 👈 point to your HTML
      },
    },
  },
  plugins: [
    !isRunningOnBrowser &&electron({
      main: {
        // Shortcut of `build.lib.entry`.
        entry: 'electron/main.ts',
      },
      preload: {
        // Shortcut of `build.rollupOptions.input`.
        // Preload scripts may contain Web assets, so use the `build.rollupOptions.input` instead `build.lib.entry`.
        input: path.join(__dirname, 'electron/preload.ts'),
      },
      // Ployfill the Electron and Node.js API for Renderer process.
      // If you want use Node.js in Renderer process, the `nodeIntegration` needs to be enabled in the Main process.
      // See 👉 https://github.com/electron-vite/vite-plugin-electron-renderer
      renderer: process.env.NODE_ENV === 'test'
        // https://github.com/electron-vite/vite-plugin-electron-renderer/issues/78#issuecomment-2053600808
        ? undefined
        : {},
    }),
  ],
})
