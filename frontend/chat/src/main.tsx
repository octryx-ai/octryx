import React from "react";
import ReactDOM from "react-dom/client";
import { AppContainer as App } from "./AppContainer";
import { startStartupRequests } from "./chat/startupRequests";
import { installStaleBuildReload } from "./staleBuild";
import "./styles.css";

installStaleBuildReload();
startStartupRequests();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
