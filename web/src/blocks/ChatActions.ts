import { createContext } from "react";

/** Lets a reply's buttons and tiles act: send runs a message now; fill puts a question in the composer for the user to send. */
export const ChatActions = createContext<{ send: (t: string) => void; fill: (t: string) => void; busy: boolean }>({ send: () => {}, fill: () => {}, busy: true });
