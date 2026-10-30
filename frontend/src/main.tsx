import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./styles.css"; // temel (eski) stiller önce; App içindeki theme.css sonra yüklenir ve üzerine yazar (ui-001)
import { App, ROUTER_FUTURE } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter future={ROUTER_FUTURE}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
