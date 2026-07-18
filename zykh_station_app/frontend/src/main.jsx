import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import "./styles/app.css";
import "./styles/stroke-draw.css";
import "./styles/settings.css";
import "./styles/admin.css";
import "./styles/design-polish.css";
import "./styles/motion-system.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
