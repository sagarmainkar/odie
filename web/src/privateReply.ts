import { createContext } from "react";

/** True inside a reply from a chat that read a signed-in page: its web images wait for a tap (signin.heldLabel). */
export const PrivateReply = createContext(false);
