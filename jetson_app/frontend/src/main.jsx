import React from "react";
import { createRoot } from "react-dom/client";
import { AdminApp } from "./app/AdminApp.jsx";
import { TerminalApp } from "./app/TerminalApp.jsx";
import "./styles.css";

function Root() {
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminApp />;
  return <TerminalApp />;
}

createRoot(document.getElementById("root")).render(<Root />);
