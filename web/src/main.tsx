import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// The two fonts ship with the app (no request to Google): Plus Jakarta Sans for text, Instrument Serif in italics.
import "@fontsource-variable/plus-jakarta-sans/wght.css";
import "@fontsource/instrument-serif/400-italic.css";
import "./styles.css";
import { initLook, startLookClock } from "./theme";
import { PRIVATE_EVENT, watchPrivate } from "./devices";

window.fetch = watchPrivate(window.fetch.bind(window), () => window.dispatchEvent(new Event(PRIVATE_EVENT)));
initLook();
startLookClock();

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
