import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AdminApp } from "./AdminApp";
import { ThemeProvider } from "./theme";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename="/admin">
      <ThemeProvider><AdminApp /></ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
);
