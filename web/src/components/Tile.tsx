// Line icons and the glossy "tile" spheres that mark where a thing comes from (mail, money, calendar…).
const P: Record<IconName, string> = {
  mail: '<path d="M4 6h16v12H4z"/><path d="m4 7 8 6 8-6"/>',
  gmail: '<path d="M4 19V7l8 6 8-6v12"/><path d="M4 7l8 6 8-6"/>',
  icloud: '<path d="M7 18a4 4 0 0 1-.5-8 5.5 5.5 0 0 1 10.6 1.3A3.4 3.4 0 0 1 17 18H7z"/>',
  rupee: '<path d="M7 5h10M7 9h10M13 19 8 13h2a4 4 0 0 0 0-8"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  cal: '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M8 3v4M16 3v4M4 10h16"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  menu: '<path d="M4 8h16M4 16h16"/>',
  play: '<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>',
  speaker: '<path d="M4 10v4h4l5 4V6L8 10z"/><path d="M16.5 9a4 4 0 0 1 0 6M19 6.5a7.5 7.5 0 0 1 0 11"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="3"/><path d="M5 15V7a2 2 0 0 1 2-2h8"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/>',
  note: '<path d="M6 4h9l4 4v12H6z"/><path d="M14 4v5h5M9 13h7M9 17h5"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.5 3.5 8.5s-1 6-3.5 8.5c-2.5-2.5-3.5-5.5-3.5-8.5s1-6 3.5-8.5z"/>',
  terminal: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m7 10 3 2-3 2M12 15h5"/>',
  chart: '<path d="M4 19h16"/><path d="m5 15 4-5 4 3 6-7"/>',
  photo: '<rect x="3" y="5" width="18" height="14" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="m4 17 5-4 4 3 3-2 4 3"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  chat: '<path d="M20 12a8 8 0 0 1-11.5 7.2L4 20l1-4.2A8 8 0 1 1 20 12z"/>',
  gear: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',  // sliders: a gear looked like the sun
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3V4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3V4z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  moon: '<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z"/>',
  sunset: '<path d="M4 18h16M7 14a5 5 0 0 1 10 0M12 4v3M4.9 8.9l1.4 1.4M19.1 8.9l-1.4 1.4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3"/>',
  send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
  wave: '<path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4"/>',
  heart: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  plane: '<path d="M10.5 13.5 3 11l1.5-1.5 7.5 1L16 6.5a2 2 0 0 1 3 3L15 13.5l1 7.5L14.5 22.5 12 15z"/>',
  bed: '<path d="M3 18V7M3 14h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5"/><circle cx="7" cy="11" r="1.6"/>',
  food: '<path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M16 21V3c-2 1.5-3 4-3 7h3"/>',
  walk: '<circle cx="13" cy="4.5" r="1.8"/><path d="M10 21l2-6 2.5 2V21M9 12l2-4 3 1 2 3M11 8l-2 5"/>',
  pin: '<path d="M12 21s-6-5.6-6-11a6 6 0 0 1 12 0c0 5.4-6 11-6 11z"/><circle cx="12" cy="10" r="2.2"/>',
  trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0zM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8 20h8M9.5 17h5"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  star: '<path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4l-4.8 2.5.9-5.4-3.9-3.8 5.4-.8z"/>',
  leaf: '<path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14M5 19l7-7"/>',
  flame: '<path d="M12 21a6 6 0 0 0 6-6c0-4-3-6-4-10-2 2-3 4-3 6-1-1-1.5-2-1.5-3C7 10 6 12.5 6 15a6 6 0 0 0 6 6z"/>',
  ticket: '<path d="M4 8a2 2 0 0 0 0 4v4h16v-4a2 2 0 0 1 0-4V4H4zM14 4v16" transform="translate(0 2) scale(1 .9)"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.01"/>',
  alert: '<path d="M12 4.5 21 19.5H3z"/><path d="M12 10.5v4M12 17v.01"/>',
};

export type IconName = "mail" | "gmail" | "icloud" | "rupee" | "bell" | "cal" | "check" | "clock" | "mic" | "up" | "plus" | "back" | "menu" | "play" | "speaker" | "copy" | "search" | "note" | "globe" | "terminal" | "chart" | "photo" | "spark" | "chat" | "gear" | "x" | "brain" | "sun" | "moon" | "sunset" | "trash" | "send" | "refresh" | "wave"
  | "heart" | "plane" | "bed" | "food" | "walk" | "pin" | "trophy" | "lock" | "star" | "leaf" | "flame" | "ticket" | "info" | "alert";
export type TileColor = "blue" | "orange" | "violet" | "yellow" | "green" | "pink" | "ink";

export const ICON_NAMES = Object.keys(P) as IconName[];

export function Icon({ name, size = 20, stroke = 2 }: { name: IconName; size?: number; stroke?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" dangerouslySetInnerHTML={{ __html: P[name] }} />;
}

export function Tile({ icon, color, small = false }: { icon: IconName; color: TileColor; small?: boolean }) {
  return <span className={`tile tile-${color} ${small ? "tile-sm" : ""}`}><Icon name={icon} size={small ? 15 : 20} stroke={2.2} /></span>;
}

const TOOL: Record<string, { icon: IconName; color: TileColor }> = {
  gmail_search: { icon: "mail", color: "blue" }, gmail_read: { icon: "mail", color: "blue" }, gmail_read_thread: { icon: "mail", color: "blue" },
  gmail_label: { icon: "mail", color: "blue" }, gmail_create_draft: { icon: "mail", color: "blue" }, gmail_send_draft: { icon: "send", color: "blue" },
  gmail_trash: { icon: "trash", color: "ink" }, search_notes: { icon: "note", color: "violet" }, search_everything: { icon: "note", color: "violet" }, read_note: { icon: "note", color: "violet" },
  task_add: { icon: "bell", color: "yellow" }, task_update: { icon: "bell", color: "yellow" }, task_list: { icon: "bell", color: "yellow" },
  now: { icon: "clock", color: "ink" }, calendar_list_events: { icon: "cal", color: "orange" }, calendar_find_free: { icon: "cal", color: "orange" },
  calendar_create_event: { icon: "cal", color: "orange" }, calendar_respond: { icon: "cal", color: "orange" }, life_admin: { icon: "rupee", color: "green" },
  fetch_memory: { icon: "brain", color: "pink" }, search_memories: { icon: "brain", color: "pink" }, update_memory: { icon: "brain", color: "pink" },
  run_shell: { icon: "terminal", color: "ink" }, web_search: { icon: "globe", color: "blue" }, web_fetch: { icon: "globe", color: "blue" },
  market_history: { icon: "chart", color: "violet" },
};

export function toolTile(tool: string): { icon: IconName; color: TileColor } {
  return TOOL[tool] ?? { icon: "spark", color: "violet" };
}
