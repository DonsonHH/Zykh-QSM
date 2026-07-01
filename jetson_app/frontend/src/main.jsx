import React from "react";
import { createRoot } from "react-dom/client";
import { AdminApp } from "./app/AdminApp.jsx";
import { StylePreview } from "./app/StylePreview.jsx";
import { TerminalApp } from "./app/TerminalApp.jsx";
import "./styles.css";

function Root() {
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminApp />;
  if (path.startsWith("/style-preview")) return <StylePreview />;
  return <TerminalApp />;
}

createRoot(document.getElementById("root")).render(<Root />);
