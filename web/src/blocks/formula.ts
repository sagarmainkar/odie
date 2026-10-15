// Formulas in a calculator block, hand-written (no library, no eval): numbers, input ids, + - * / ^, parentheses,
// comparisons (< <= > >= == !=, giving 1 or 0) and a fixed list of helpers. Nothing else: no property access (a.b),
// no strings, no assignment, no function definitions. A name is looked up only among the calculator's input values
// (a Map), so "constructor", "this" or "__proto__" are just unknown names.
//   "emi(p, r, n) * n * 12 - p" with p = 4000000, r = 8.5, n = 20 → 4331103 (the total interest)

export type Node =
  | { kind: "number"; value: number }
  | { kind: "name"; name: string }
  | { kind: "negate"; arg: Node }
  | { kind: "binary"; op: string; left: Node; right: Node }
  | { kind: "call"; fn: string; args: Node[] };

const MAX_LENGTH = 300;
const MAX_DEPTH = 30;

/** How many arguments each helper takes: [fewest, most]. */
const HELPERS: Record<string, [number, number]> = {
  min: [1, 10], max: [1, 10], round: [1, 2], abs: [1, 1], if: [3, 3], emi: [3, 3], sip: [3, 3], pct: [2, 2],
  prepay_years: [4, 4], prepay_interest: [4, 4],
};

export function isHelper(name: string): boolean {
  return Object.hasOwn(HELPERS, name);
}

// One token: a number (1, 8.5, .5, 1e6), a name, or an operator. Anything else (a quote, a dot after a name, ;) stops.
const TOKEN = /\s*(?:((?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|[-+*/^(),<>]))/iy;

function tokenize(text: string): string[] {
  if (text.length > MAX_LENGTH) throw new Error("formula too long");
  const tokens: string[] = [];
  TOKEN.lastIndex = 0;
  while (TOKEN.lastIndex < text.length) {
    const from = TOKEN.lastIndex;
    if (/^\s*$/.test(text.slice(from))) break;
    const m = TOKEN.exec(text);
    if (!m) throw new Error(`can't read "${text.slice(from).trim().slice(0, 12)}"`);
    tokens.push(m[1] ?? m[2] ?? m[3]);
  }
  return tokens;
}

/** A formula's text → its tree; throws with a reason when it isn't one. "2 + p * 3" → (2 + (p * 3)) */
export function parseFormula(text: string): Node {
  const tokens = tokenize(text);
  let at = 0;
  let depth = 0;
  const peek = () => tokens[at];
  const take = (want?: string) => {
    const t = tokens[at];
    if (want !== undefined && t !== want) throw new Error(`expected ${want}`);
    at += 1;
    return t;
  };
  const deeper = () => {
    depth += 1;
    if (depth > MAX_DEPTH) throw new Error("formula nests too deep");
  };

  // Lowest binding first: a comparison of sums, a sum of products, a product of powers.
  function comparison(): Node {
    const left = sum();
    if (["<", "<=", ">", ">=", "==", "!="].includes(peek())) return { kind: "binary", op: take(), left, right: sum() };
    return left;
  }
  function sum(): Node {
    let left = product();
    while (peek() === "+" || peek() === "-") left = { kind: "binary", op: take(), left, right: product() };
    return left;
  }
  function product(): Node {
    let left = unary();
    while (peek() === "*" || peek() === "/") left = { kind: "binary", op: take(), left, right: unary() };
    return left;
  }
  // -2^2 is -(2^2) = -4, as in maths; 2^-1 works too.
  function unary(): Node {
    deeper();
    let node: Node;
    if (peek() === "-") { take(); node = { kind: "negate", arg: unary() }; }
    else if (peek() === "+") { take(); node = unary(); }
    else node = power();
    depth -= 1;
    return node;
  }
  function power(): Node {
    const base = primary();
    if (peek() === "^") { take(); return { kind: "binary", op: "^", left: base, right: unary() }; }
    return base;
  }
  function primary(): Node {
    const t = take();
    if (t === undefined) throw new Error("formula ends too soon");
    if (/^[\d.]/.test(t)) return { kind: "number", value: Number(t) };
    if (t === "(") { const inside = comparison(); take(")"); return inside; }
    if (!/^[A-Za-z_]/.test(t)) throw new Error(`unexpected "${t}"`);
    if (peek() !== "(") return { kind: "name", name: t };
    if (!isHelper(t)) throw new Error(`unknown helper ${t}()`);
    take("(");
    const args = [comparison()];
    while (peek() === ",") { take(); args.push(comparison()); }
    take(")");
    const [fewest, most] = HELPERS[t];
    if (args.length < fewest || args.length > most) throw new Error(`${t}() takes ${fewest === most ? fewest : `${fewest}-${most}`} values`);
    return { kind: "call", fn: t, args };
  }

  const tree = comparison();
  if (at < tokens.length) throw new Error(`unexpected "${tokens[at]}"`);
  return tree;
}

/** The input names a formula uses: "emi(p, r, n) - p" → ["p", "r", "n"] */
export function namesIn(node: Node, found: Set<string> = new Set()): string[] {
  if (node.kind === "name") found.add(node.name);
  if (node.kind === "negate") namesIn(node.arg, found);
  if (node.kind === "binary") { namesIn(node.left, found); namesIn(node.right, found); }
  if (node.kind === "call") node.args.forEach((a) => namesIn(a, found));
  return [...found];
}

/** A formula's value with these inputs, or null when it can't be worked out (it doesn't parse, uses an unknown name,
 *  divides by zero, or the answer isn't a finite number). "p / n" with n = 0 → null; "1 +" → null */
export function evaluate(formula: string | Node, values: ReadonlyMap<string, number>): number | null {
  try {
    const tree = typeof formula === "string" ? parseFormula(formula) : formula;
    const result = valueOf(tree, values);
    if (!Number.isFinite(result)) return null;
    return result;
  } catch {
    return null;
  }
}

function valueOf(node: Node, values: ReadonlyMap<string, number>): number {
  switch (node.kind) {
    case "number": return node.value;
    case "name": {
      const v = values.get(node.name);
      if (v === undefined) throw new Error(`unknown name ${node.name}`);
      return v;
    }
    case "negate": return -valueOf(node.arg, values);
    case "binary": return binary(node.op, valueOf(node.left, values), valueOf(node.right, values));
    case "call": {
      // if() works out only the branch it picks, so if(n == 0, 0, p / n) is fine when n is 0.
      if (node.fn === "if") return valueOf(node.args[0], values) !== 0 ? valueOf(node.args[1], values) : valueOf(node.args[2], values);
      return helper(node.fn, node.args.map((a) => valueOf(a, values)));
    }
  }
}

function binary(op: string, a: number, b: number): number {
  if (op === "+") return a + b;
  if (op === "-") return a - b;
  if (op === "*") return a * b;
  if (op === "/") return divide(a, b);
  if (op === "^") return a ** b;
  const comparisons: Record<string, boolean> = { "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a === b, "!=": a !== b };
  return comparisons[op] ? 1 : 0;
}

function divide(a: number, b: number): number {
  if (b === 0) throw new Error("division by zero");
  return a / b;
}

function helper(fn: string, args: number[]): number {
  switch (fn) {
    case "min": return Math.min(...args);
    case "max": return Math.max(...args);
    case "abs": return Math.abs(args[0]);
    case "round": return roundTo(args[0], args[1] ?? 0);
    case "pct": return divide(args[0], args[1]) * 100;
    case "emi": return emi(args[0], args[1], args[2]);
    case "sip": return sip(args[0], args[1], args[2]);
    case "prepay_years": return prepay(args[0], args[1], args[2], args[3]).months / 12;
    case "prepay_interest": return prepay(args[0], args[1], args[2], args[3]).interest;
  }
  throw new Error(`unknown helper ${fn}()`);
}

/** round(2.345, 2) → 2.35; round(1234.5) → 1235; round(1234, -2) → 1200 */
function roundTo(x: number, digits: number): number {
  const scale = 10 ** Math.round(digits);
  return Math.round(x * scale) / scale;
}

/**
 * The monthly payment on a loan repaid in equal instalments (reducing balance, the way Indian banks quote an EMI):
 * P · r · (1 + r)^n / ((1 + r)^n − 1), with r the monthly rate (rate_pct / 12 / 100) and n the months (years · 12).
 *   emi(4000000, 8.5, 20) → 34712.9, shown as ₹34,713 (₹40 lakh at 8.5% for 20 years);  at 0% it is simply P / n
 */
export function emi(principal: number, ratePct: number, years: number): number {
  const months = years * 12;
  if (months <= 0) throw new Error("emi needs a term");
  const r = ratePct / 12 / 100;
  if (r === 0) return principal / months;
  const growth = (1 + r) ** months;
  return (principal * r * growth) / (growth - 1);
}

/**
 * What a monthly SIP is worth at the end: each payment is made at the START of its month, so every payment earns
 * that month's return too (an annuity due): M · ((1 + i)^n − 1) / i · (1 + i), with i = rate_pct / 12 / 100, n = years · 12.
 *   sip(10000, 12, 10) → 2323391 (₹10,000 a month at 12% for 10 years);  at 0% it is M · n
 */
export function sip(monthly: number, ratePct: number, years: number): number {
  const months = years * 12;
  const i = ratePct / 12 / 100;
  if (i === 0) return monthly * months;
  return (monthly * ((1 + i) ** months - 1) / i) * (1 + i);
}

/**
 * Paying a loan off early with a lump sum once a year: the EMI for the full term is paid every month, and at the end
 * of every 12th month `yearlyExtra` more goes straight off the principal. Worked month by month: the month's interest
 * is added to what's owed, then the EMI comes off (the last payment is only what's left). Gives the months it takes
 * and the total interest paid. In a formula: prepay_years(p, r, n, extra) is months / 12, prepay_interest(…) the interest.
 *   prepay(4000000, 8.5, 20, 0)      → {months: 240, interest: 4331103}  (no extra: the plain 20-year loan)
 *   prepay(4000000, 8.5, 20, 200000) → {months: 120, interest: 1949956}  (₹2 lakh a year: done in 10 years)
 */
export function prepay(principal: number, ratePct: number, years: number, yearlyExtra: number): { months: number; interest: number } {
  if (yearlyExtra < 0) throw new Error("the yearly extra can't be negative");
  const monthly = emi(principal, ratePct, years);
  const r = ratePct / 12 / 100;
  const lastMonth = Math.ceil(years * 12);  // the EMI alone clears the loan by then
  let owed = principal;
  let interest = 0;
  let months = 0;
  while (owed > 0.005 && months < lastMonth) {
    months += 1;
    const thisMonth = owed * r;
    interest += thisMonth;
    owed = Math.max(0, owed + thisMonth - monthly);
    if (months % 12 === 0) owed = Math.max(0, owed - yearlyExtra);
  }
  return { months, interest };
}
