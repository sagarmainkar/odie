import { createContext } from "react";

/** True for blocks drawn inside a section's card: a table or list then drops its own card so cards don't nest. */
export const InCard = createContext(false);
