import { describe, expect, it } from "vitest";
import { howChatShowsFence } from "./fenceShown";

describe("howChatShowsFence", () => {
  it("draws a blocks fence, a lone block object too", () => {
    expect(howChatShowsFence("odie-blocks", '[{"type":"divider"}]').as).toBe("blocks");
    expect(howChatShowsFence("odie-blocks", '{"type":"callout","tone":"tip","text":"Hi"}').as).toBe("blocks");
  });
  it("waits on a blocks fence still streaming in, and calls a finished broken one broken", () => {
    expect(howChatShowsFence("odie-blocks", '[{"type":"divider"}').as).toBe("waiting");
    expect(howChatShowsFence("odie-blocks", '[{"type": divider}]').as).toBe("broken");
  });
  it("draws photos and charts, in their own fences and in json ones", () => {
    const images = '{"images":[{"url":"https://example.com/a.jpg"}]}';
    expect(howChatShowsFence("odie-images", images).as).toBe("images");
    expect(howChatShowsFence("json", images).as).toBe("images");
    const chart = '{"type":"bar","title":"t","x":["a","b"],"series":[{"name":"s","data":[1,2]}]}';
    expect(howChatShowsFence("odie-chart", chart).as).toBe("chart");
    expect(howChatShowsFence("json", chart).as).toBe("chart");
  });
  it("draws a mermaid fence as a diagram, even one with a mistake (that shows its text and a note)", () => {
    expect(howChatShowsFence("mermaid", "flowchart TD\n  A --> B").as).toBe("diagram");
    expect(howChatShowsFence("mermaid", "flowchart TD\n  A -->").as).toBe("diagram");
  });
  it("shows anything else as code", () => {
    expect(howChatShowsFence("json", '{"a": 1}').as).toBe("code");
    expect(howChatShowsFence("python", "print(1)").as).toBe("code");
    expect(howChatShowsFence("odie-images:", '{"images": []}').as).toBe("code");
  });
});
