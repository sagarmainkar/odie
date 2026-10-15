import type { IconName, TileColor } from "./components/Tile";
import { shown, type Caps } from "./capabilities";

export type Idea = { q: string; from: string; icon: IconName; color: TileColor; needs?: string };

/** Things to ask on an empty chat; one that needs a feature the install doesn't have isn't offered. */
export const IDEAS: Idea[] = [
  { q: "What can you do?", from: "About Odie", icon: "spark", color: "ink" },
  { q: "Plan a weekend trip for me", from: "Travel itinerary", icon: "plane", color: "violet" },
  { q: "What's on today?", from: "Your calendar", icon: "cal", color: "blue", needs: "calendar" },
  { q: "Anything in mail I should answer?", from: "Your inbox", icon: "mail", color: "orange", needs: "mail" },
  { q: "What did I spend this week?", from: "Your messages", icon: "rupee", color: "green", needs: "money" },
  { q: "Track Arsenal's next match and tell me the score", from: "Trackers", icon: "bell", color: "yellow" },
];

/** The market to ask about where the user is (the computer's region); none where Odie can't tell. */
const MARKET: Record<string, string> = { IN: "How is NIFTY doing this week?", US: "How is the NASDAQ doing this week?" };

export function ideasFor(caps: Caps, country = ""): Idea[] {
  const market = MARKET[country];
  return shown(market ? [...IDEAS, { q: market, from: "Markets", icon: "chart", color: "pink" }] : IDEAS, caps);
}
