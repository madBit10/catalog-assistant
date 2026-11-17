import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Concept: DEV PROXY. The React dev server (port 5173) forwards API calls to
// FastAPI (port 8000). To the browser it's ONE origin, so no CORS setup is
// needed, and the code just calls "/batches", like it will in production.
// Example: fetch("/batches") in React -> http://localhost:8000/batches
const api = "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/auth": api,
      "/batches": api,
      "/items": api,
    },
  },
});
