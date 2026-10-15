// A fence's JSON as models write it. Most fences are plain JSON. When one isn't, two slips seen in real replies are
// mended and the text is read again; nothing else is guessed, so a fence that still isn't JSON stays unread (and the
// chat shows "Couldn't draw this", as before). Each mend touches only spots that can't be valid JSON, so a fence that
// already reads is never changed.

/**
 * The text read as JSON, or undefined when it isn't JSON even after mending. Tries, in order: the text as written,
 * each mend on its own, then both together.
 *   '{"data": [1, 2]}'                         → {data: [1, 2]}            (as written)
 *   '{"data": [37,846,000, 27,950,000]}'       → {data: [37846000, 27950000]}
 *   '[{"text": "Jacket (warm!), "checked": false}]' → [{text: "Jacket (warm!)", checked: false}]
 *   '[{"type": "table"'                        → undefined                  (cut off: still streaming in)
 */
export function readJson(text: string): unknown {
  const tries = [text, closeUnclosedStrings(text), joinThousands(text), joinThousands(closeUnclosedStrings(text))];
  for (const attempt of tries) {
    try {
      return JSON.parse(attempt);
    } catch {
      // not JSON yet: try the next mend
    }
  }
  return undefined;
}

// A comma and a key ( , "checked": ) right after something that can't end a JSON value. In valid JSON the character
// before such a comma always ends a value: a closing quote, a digit, } or ], or the last letter of true, false or null.
const KEY_AFTER_OPEN_STRING = /(?<!["\d}\]\s]|true|false|null)(,\s*"[A-Za-z_]\w*"\s*:)/g;

/**
 * Closes a string the model forgot to close before the next key (Gemma 4, a packing list): the quote goes back right
 * before the comma. A comma and key after a value's real end are left alone.
 *   '{"text": "Heavy woolens (it gets cold!), "checked": false}' → '{"text": "Heavy woolens (it gets cold!)", "checked": false}'
 *   '{"text": "Socks", "checked": false}'                        → unchanged
 */
export function closeUnclosedStrings(text: string): string {
  return text.replace(KEY_AFTER_OPEN_STRING, '"$1');
}

// A string in JSON: a quote, then anything but a quote or backslash, or a backslash and the character it escapes.
const STRING = /"(?:[^"\\]|\\.)*"/g;
// A number with thousands commas: 1 to 3 digits, then groups of exactly 3 (37,846,000), not part of a longer number.
const THOUSANDS = /(?<![\d.])\d{1,3}(?:,\d{3}(?!\d))+(?![\d.])/g;

/**
 * Numbers written with thousands commas (Gemma 4, a chart: "data": [37,846,000, 27,950,000]) become plain numbers.
 * JSON reads 37,846,000 as three numbers, and "000" isn't one at all (no leading zeros), which is why the fence fails.
 * That leading-zero group is the proof the text writes thousands with commas; without one, nothing is joined, because
 * [12,105,230] could just as well be three numbers. Text inside strings ("₹34,689") is never touched.
 *   '{"data": [37,846,000, 27,950,000], "unit": "₹"}' → '{"data": [37846000, 27950000], "unit": "₹"}'
 *   '{"data": [12,105,230]}'                          → unchanged (no group starts with 0: three numbers)
 *   '{"text": "₹1,000 a month"}'                       → unchanged (inside a string)
 */
export function joinThousands(text: string): string {
  const outside = text.split(STRING);
  const hasThousands = outside.some((part) => [...part.matchAll(THOUSANDS)].some((m) => startsAGroupWithZero(m[0])));
  if (!hasThousands) return text;

  const strings = text.match(STRING) ?? [];
  const joined: string[] = [];
  outside.forEach((part, i) => {
    joined.push(part.replace(THOUSANDS, (n) => n.replaceAll(",", "")));
    if (i < strings.length) joined.push(strings[i]);
  });
  return joined.join("");
}

/** "37,846,000" → true (the "000" group);  "12,105,230" → false */
function startsAGroupWithZero(number: string): boolean {
  return number.split(",").slice(1).some((group) => group.startsWith("0"));
}
