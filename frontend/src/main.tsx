import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import { AuthProvider } from "./auth.tsx";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Every page inside can call useAuth() */}
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
);
