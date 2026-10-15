/** Files a tool attached to a reply (make_file, attach_file, the documents skill): how they're described on the card. */
export type FileKind = "slides" | "doc" | "pdf" | "sheet" | "web" | "calendar" | "data" | "text" | "picture" | "video" | "audio" | "other";

const BY_EXT: Record<string, FileKind> = {
  pptx: "slides", ppt: "slides", key: "slides", docx: "doc", doc: "doc", pdf: "pdf", csv: "sheet", xlsx: "sheet", xls: "sheet",
  html: "web", htm: "web", ics: "calendar", json: "data", md: "text", txt: "text",
  png: "picture", jpg: "picture", jpeg: "picture", webp: "picture", gif: "picture", svg: "picture",
  mp4: "video", webm: "video", mov: "video", m4v: "video", mp3: "audio", m4a: "audio", wav: "audio", ogg: "audio", aac: "audio",
};
const LABEL: Record<FileKind, string> = {
  slides: "PowerPoint", doc: "Word document", pdf: "PDF", sheet: "Spreadsheet", web: "Web page", calendar: "Calendar event", data: "Data",
  text: "Text", picture: "Picture", video: "Video", audio: "Audio", other: "File",
};

export function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function kindOf(filename: string): FileKind {
  const ext = filename.includes(".") ? filename.split(".").pop()!.toLowerCase() : "";
  return BY_EXT[ext] ?? "other";
}

export const typeLabel = (k: FileKind) => LABEL[k];
