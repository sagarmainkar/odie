import { useContext } from "react";
import { Blocks } from "./Blocks";
import type { Block } from "./parse";
import { FencePlace, ReplyPlace, fenceNumber } from "./SavedPlace";
import type { Reply } from "./savedState";

/** A fence's blocks, told which reply and fence they are in. `offset`: where the fence starts in the reply's text. */
export function BlocksFence({ blocks, source, offset }: { blocks: Block[]; source: string; offset: number }) {
  const info = useContext(ReplyPlace);
  let reply: Reply | null = null;
  if (info?.sessionId && info.messageKey) reply = { sessionId: info.sessionId, messageKey: info.messageKey };
  const fence = fenceNumber(info?.text ?? "", offset);
  return (
    <FencePlace.Provider value={{ reply, fence }}>
      <Blocks blocks={blocks} source={source} />
    </FencePlace.Provider>
  );
}
