import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard runs on http://localhost:5173 and calls FastAPI at http://localhost:8000
// (override with VITE_API_BASE). The backend's CORS allows this origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
