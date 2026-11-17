/** Where the long-term memory file is, as Settings shows it: the file's name on one line and its folder, shortened, on
 *  the next (the full path goes in the row's title). */
export type MemoryPlace = { name: string; folder: string };

const LONGEST_FOLDER = 32;  // characters; about one line of the row's 12px meta text on a phone

/** The folder with the user's home as "~": "/Users/sam/.odie" -> "~/.odie"; "/home/sam/.odie" -> "~/.odie";
 *  "/srv/odie" -> "/srv/odie". */
function withHomeAsTilde(folder: string): string {
  return folder.replace(/^\/(Users|home)\/[^/]+/, "~");
}

/** A long folder with its middle left out: where it starts, then its last two folders.
 *    "~/Library/Application Support/Odie/data/memory" -> "~/…/data/memory"
 *    "/private/tmp/a/b/c/check/home"                    -> "/private/…/check/home"
 *    "~/.odie" (short)                                   -> "~/.odie" */
function elided(folder: string): string {
  if (folder.length <= LONGEST_FOLDER) return folder;
  const parts = folder.split("/");  // "/private/tmp/x" -> ["", "private", "tmp", "x"]
  const startParts = parts[0] === "" ? 2 : 1;  // "/private" or "~"
  if (parts.length <= startParts + 2) return folder;  // nothing in the middle to leave out
  return [...parts.slice(0, startParts), "…", ...parts.slice(-2)].join("/");
}

/** The file's name and its folder. In the vault (`vaultDir` holds the file) the folder starts at the vault's own name,
 *  as Obsidian shows it; elsewhere home is "~". A long folder loses its middle.
 *    "/Users/sam/.odie/memories.md", no vault                       -> memories.md · ~/.odie
 *    "/Users/sam/Notes Vault/Odie/memories.md", vault ".../Notes Vault" -> memories.md · Notes Vault/Odie */
export function memoryPlace(file: string, vaultDir: string): MemoryPlace {
  const cut = file.lastIndexOf("/");
  const name = file.slice(cut + 1);
  const fullFolder = file.slice(0, Math.max(cut, 0));
  const inVault = vaultDir !== "" && file.startsWith(vaultDir);
  let folder = withHomeAsTilde(fullFolder);
  if (inVault) {
    const vaultRoot = vaultDir.replace(/\/+$/, "");  // "/Users/sam/Notes Vault/" -> "/Users/sam/Notes Vault"
    const vaultName = vaultRoot.slice(vaultRoot.lastIndexOf("/") + 1);
    folder = vaultName + fullFolder.slice(vaultRoot.length);
  }
  return { name, folder: elided(folder) };
}
