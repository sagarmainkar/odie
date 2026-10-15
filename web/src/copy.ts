/** Copy text to the clipboard. The Clipboard API exists only on a secure page (https or localhost) and can refuse;
 * then a hidden text box and the older copy command, which work on any page. False when neither did. */
type Clip = { writeText: (text: string) => Promise<void> } | undefined;

function selectAndCopy(text: string): boolean {
  const box = document.createElement("textarea");
  box.value = text;
  box.setAttribute("readonly", "");
  box.style.position = "fixed";
  box.style.opacity = "0";
  document.body.appendChild(box);
  box.select();
  box.setSelectionRange(0, text.length);  // iOS Safari
  try { return document.execCommand("copy"); }
  catch { return false; }
  finally { box.remove(); }
}

export async function copyText(text: string, deps: { clipboard?: Clip; fallback?: (text: string) => boolean } = {}): Promise<boolean> {
  const clipboard = "clipboard" in deps ? deps.clipboard : (typeof navigator !== "undefined" ? navigator.clipboard : undefined);
  const fallback = deps.fallback ?? selectAndCopy;
  if (clipboard) {
    try { await clipboard.writeText(text); return true; }
    catch { /* refused: try the older way */ }
  }
  return fallback(text);
}
