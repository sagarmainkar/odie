import { useContext, useState, type ReactNode } from "react";
import { ChartBlock } from "../components/ChartBlock";
import { Icon } from "../components/Tile";
import { Badge, Bar, Button, Callout, Divider, Heading, LinkLine, Picture, Text } from "./Atoms";
import { Calculator } from "./Calculator";
import { ChatActions } from "./ChatActions";
import { Checklist } from "./Checklist";
import { Grid, Row, Section } from "./Containers";
import { fenceAsText } from "./fenceText";
import { Flip } from "./Flip";
import { Form } from "./Form";
import { Heatmap } from "./Heatmap";
import { FenceValues, startingValues } from "./fenceValues";
import { List } from "./List";
import { Progress, Streak, Tiles, Timeline } from "./Rich";
import { Table } from "./Table";
import { KpiCard, Kpis } from "./Kpis";
import type { Block } from "./parse";

function Actions({ items }: { items: { label: string; run: string }[] }) {
  const { send, busy } = useContext(ChatActions);
  return (
    <div className="flex flex-wrap gap-2 my-2">
      {items.map((a) => (
        <button key={a.label} type="button" disabled={busy} onClick={() => send(a.run)} className="pill pill-solid h-10 text-[14px] shadow-none disabled:opacity-40">
          <Icon name="spark" size={15} /> {a.label}
        </button>
      ))}
    </div>
  );
}

function Source({ text, url }: { text: string; url?: string }) {
  if (!url) return <div className="text-[11.5px] text-dim my-1.5">{text}</div>;
  return <div className="text-[11.5px] text-dim my-1.5"><a href={url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{text}</a></div>;
}

// Each kind and how it is drawn. Containers draw their children with drawAll, which comes back through this map.
type Drawers = { [K in Block["type"]]: (block: Extract<Block, { type: K }>) => ReactNode };
const DRAW: Drawers = {
  chart: (b) => <ChartBlock spec={b.spec} />,
  kpis: (b) => <Kpis items={b.items} />,
  actions: (b) => <Actions items={b.items} />,
  source: (b) => <Source text={b.text} url={b.url} />,
  tiles: (b) => <Tiles items={b.items} />,
  progress: (b) => <Progress {...b} />,
  streak: (b) => <Streak {...b} />,
  timeline: (b) => <Timeline {...b} />,
  flip: (b) => <Flip {...b} />,
  heatmap: (b) => <Heatmap {...b} />,
  callout: (b) => <Callout {...b} />,
  table: (b) => <Table {...b} />,
  list: (b) => <List {...b} />,
  checklist: (b) => <Checklist {...b} />,
  calculator: (b) => <Calculator {...b} />,
  form: (b) => <Form {...b} />,
  heading: (b) => <Heading text={b.text} />,
  text: (b) => <Text text={b.text} />,
  badge: (b) => <Badge text={b.text} tone={b.tone} />,
  button: (b) => <Button {...b} />,
  link: (b) => <LinkLine text={b.text} url={b.url} />,
  image: (b) => <Picture url={b.url} caption={b.caption} />,
  stat: (b) => <div className="my-2"><KpiCard item={b} /></div>,
  bar: (b) => <Bar {...b} />,
  divider: () => <Divider />,
  row: (b) => <Row kinds={b.children.map((c) => c.type)}>{drawAll(b.children)}</Row>,
  section: (b) => <Section title={b.title} collapsed={b.collapsed}>{drawAll(b.children)}</Section>,
  grid: (b) => <Grid>{drawAll(b.children)}</Grid>,
};

function BlockView({ block }: { block: Block }) {
  const draw = DRAW[block.type] as (b: Block) => ReactNode;
  return draw(block);
}

function drawAll(blocks: Block[]): ReactNode[] {
  return blocks.map((b, i) => <BlockView key={i} block={b} />);
}

/** A skill's visual reply: each block drawn from the shared kit, in order. When nothing in the fence could be drawn,
 *  a small note says so, and `source` (the fence's text) can be read as plain lines instead. */
export function Blocks({ blocks, source }: { blocks: Block[]; source?: string }) {
  if (!blocks.length) return <CouldNotDraw source={source} />;
  return <ValuesOfFence blocks={blocks}><div className="blocks">{drawAll(blocks)}</div></ValuesOfFence>;
}

/** The fence's shared values: each calculator input starts at the model's value; a slider the user moved keeps its
 *  own. Not saved: a reload starts again from the model's values. */
function ValuesOfFence({ blocks, children }: { blocks: Block[]; children: ReactNode }) {
  const [moved, setMoved] = useState<Record<string, number>>({});
  const values = startingValues(blocks);
  for (const [id, value] of Object.entries(moved)) {
    if (values.has(id)) values.set(id, value);
  }
  const set = (id: string, value: number) => setMoved((before) => ({ ...before, [id]: value }));
  return <FenceValues.Provider value={{ values, set }}>{children}</FenceValues.Provider>;
}

function CouldNotDraw({ source }: { source?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="blocks">
      <div className="my-2 rounded-[16px] bg-well px-3.5 py-2.5 text-[13.5px] text-muted">
        <div className="flex items-center gap-2">
          <Icon name="alert" size={15} stroke={2.2} />
          <span className="flex-1">Couldn’t draw this</span>
          {source && (
            <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="hit font-semibold text-ink-2">
              {open ? "Hide text" : "Show as text"}
            </button>
          )}
        </div>
        {open && source && <div className="mt-2 whitespace-pre-wrap text-[14px] leading-[20px] text-ink-2">{fenceAsText(source)}</div>}
      </div>
    </div>
  );
}
