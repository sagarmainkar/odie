import { useContext, type ComponentProps } from "react";
import { ICON_NAMES, Icon, type IconName } from "../components/Tile";
import { FenceValues, fillValues } from "./fenceValues";
import { badgeClass, splitInline, type Piece } from "./inlineSyntax";

/** Block text with its inline syntax drawn: :badge[…] pills, :icon[…] icons, **bold** and https links; in a fence with
 *  a calculator, {formula} placeholders show live values too. */
export function InlineText({ text }: { text: string }) {
  const { values } = useContext(FenceValues);
  const pieces = splitInline(fillValues(text, values));  // values first: a formula's * mustn't be read as **bold**
  return <>{pieces.map((piece, i) => <InlinePiece key={i} piece={piece} />)}</>;
}

function InlinePiece({ piece }: { piece: Piece }) {
  switch (piece.kind) {
    case "text":
      return piece.text;
    case "badge":
      return <span className={`chip chip-inline ${badgeClass(piece.tone)}`}>{piece.text}</span>;
    case "icon":
      return <span className="inline-icon"><Icon name={piece.name} size={15} stroke={2.2} /></span>;
    case "bold":
      return <b className="font-bold">{piece.text}</b>;
    case "link":
      return <a href={piece.url} target="_blank" rel="noreferrer" className="text-ember-text underline underline-offset-2">{piece.text}</a>;
  }
}

/** The <span> renderer for reply Markdown: draws the icons remarkInline marked with data-icon; other spans as they are. */
export function MarkdownSpan({ node: _node, children, ...rest }: ComponentProps<"span"> & { node?: unknown }) {
  const name = (rest as Record<string, unknown>)["data-icon"];
  if (typeof name === "string" && (ICON_NAMES as string[]).includes(name)) {
    return <span className="inline-icon"><Icon name={name as IconName} size={16} stroke={2.2} /></span>;
  }
  return <span {...rest}>{children}</span>;
}
