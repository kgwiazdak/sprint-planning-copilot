import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
    plugins: [react()],
    build: {
        rollupOptions: {
            output: {
                manualChunks: {
                    'react-vendor': ['react', 'react-dom', 'react-router-dom'],
                    'mui-vendor': ['@mui/material', '@mui/icons-material', '@mui/x-data-grid'],
                    'form-vendor': ['react-hook-form', '@hookform/resolvers', 'zod'],
                },
            },
        },
        chunkSizeWarningLimit: 1000,
    },
})
