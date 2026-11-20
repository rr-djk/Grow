import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { LangProvider } from "./lib/i18n";
import { AppProvider } from "./lib/store";
import "./styles.css";

const basename = window.location.pathname.match(/^\/(?:abs)?proxy\/\d+/)?.[0] ?? "/";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <LangProvider>
        <AppProvider>
          <App />
        </AppProvider>
      </LangProvider>
    </BrowserRouter>
  </StrictMode>,
);
