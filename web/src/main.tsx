import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// The fonts ship with the app (no request to Google), so they work offline too: Plus Jakarta Sans for text,
// Instrument Serif in italics; for the Newspaper style, Fraunces (headings, with its optical sizes) and Newsreader
// (reading, with its italic). A browser fetches a font only when a page uses it.
import "@fontsource-variable/plus-jakarta-sans/wght.css";
import "@fontsource/instrument-serif/400-italic.css";
import "@fontsource-variable/fraunces/opsz.css";
import "@fontsource-variable/newsreader/wght.css";
import "@fontsource-variable/newsreader/wght-italic.css";
import "./styles.css";
import { initLook, startLookClock } from "./theme";
import { PRIVATE_EVENT, watchPrivate } from "./devices";

window.fetch = watchPrivate(window.fetch.bind(window), () => window.dispatchEvent(new Event(PRIVATE_EVENT)));
initLook();
startLookClock();

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
