// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReplyText } from "../screens/Chat";
import { visualsIn } from "../share";

describe("a reply's visual pieces", () => {
  it("are the drawn parts of the bubble, in order, and none for words alone", () => {
    const reply = "Financials dragged.\n\n```odie-blocks\n[{\"type\": \"heatmap\", \"title\": \"Sectors\", \"rows\": [\"Fin\"], \"cols\": [\"09:15\"], \"values\": [[-0.7]]}]\n```\n\n| Sector | Move |\n|---|---|\n| Fin | -0.7 |\n";
    const bubble = document.createElement("div");
    bubble.innerHTML = renderToStaticMarkup(<ReplyText text={reply} />);
    expect(visualsIn(bubble).map((p) => p.dataset.visual)).toEqual(["blocks", "table"]);
    expect(bubble.querySelectorAll("[data-visual='blocks'] [data-share-hide]")).toHaveLength(1);  // the enlarge button stays out of the picture
    const words = document.createElement("div");
    words.innerHTML = renderToStaticMarkup(<ReplyText text="Just words." />);
    expect(visualsIn(words)).toEqual([]);
    expect(visualsIn(null)).toEqual([]);
  });
});
