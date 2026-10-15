// An ```odie-svg fence: a drawing the model wrote as SVG (an illustration, an icon, a diagram no other block makes,
// a small animation with SMIL or CSS inside it). Drawn inline after DOMPurify's SVG profile has taken out anything
// that could run or reach out: scripts, event handlers, script links, foreign HTML. SMIL's animation tags are let
// back in (the profile drops them), minus any that would animate a link or carry a script address.
import DOMPurify from "dompurify";

const SMIL_TAGS = ["animate", "animateTransform", "animateMotion", "set", "mpath"];
const SMIL_ATTRS = ["attributeName", "attributeType", "values", "dur", "repeatCount", "repeatDur", "begin", "end", "from", "to", "by",
  "keyTimes", "keySplines", "calcMode", "additive", "accumulate", "restart", "path", "rotate", "keyPoints", "origin"];
const SCRIPTY = /javascript:|data:text\/html|vbscript:/i;

/**
 * The SVG safe to put in the page, or null when the text isn't an SVG document.
 *   '<svg …><rect/><script>x()</script></svg>' → '<svg …><rect></rect></svg>'
 *   '<svg …><rect><animate attributeName="width" …/></rect></svg>' → kept, animation and all
 *   '<svg …><a><set attributeName="href" to="javascript:…"/></a></svg>' → the set is dropped
 *   '<div>hi</div>' → null;  '' → null
 */
export function cleanSvg(code: string): string | null {
  const text = (code ?? "").trim();
  if (!/^(<\?xml[^>]*>\s*)?(<!--[\s\S]*?-->\s*)*<svg[\s>]/i.test(text)) return null;
  const out = DOMPurify.sanitize(text, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: SMIL_TAGS, ADD_ATTR: SMIL_ATTRS });
  if (!/^<svg[\s>]/i.test(out.trim())) return null;
  return withoutScriptyAnimation(out);
}

/** SMIL may set any attribute: an animation that targets a link, or whose values carry a script address, goes; so
 * does one left with nothing to animate (DOMPurify strips the attributes it dislikes, leaving an empty tag). */
function withoutScriptyAnimation(svg: string): string {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  for (const el of Array.from(doc.querySelectorAll(SMIL_TAGS.join(",")))) {
    const target = el.getAttribute("attributeName") ?? "";
    const scripty = Array.from(el.attributes).some((a) => SCRIPTY.test(a.value.replace(/\s+/g, "")));
    const aims = el.tagName.toLowerCase() === "mpath" || el.tagName.toLowerCase() === "animatemotion" || target;
    if (!aims || /href/i.test(target) || scripty) el.remove();
  }
  return new XMLSerializer().serializeToString(doc.documentElement);
}

/** Whether a streaming fence has its closing tag yet: '<svg>…</svg>' → true; '<svg><rect' → false. */
export function svgComplete(code: string): boolean {
  return /<\/svg>\s*$/i.test((code ?? "").trim());
}
