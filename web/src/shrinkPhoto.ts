// Photos are shrunk on the phone before they're sent. A phone photo is 3-10 MB and the server keeps only a
// 1280 px JPEG of it (odie/app/images.py MAX_EDGE), so sending the original wasted the upload: six book pages took a
// long time on the phone (27 Oct). Shrunk here, each is about 300 KB.

export const MAX_EDGE = 1280; // the same long edge the server keeps
const QUALITY = 0.92; // high, because the server compresses it once more
const SMALL_ENOUGH = 600 * 1024; // a file this small goes as it is

/** The size a photo is drawn at: its long edge at most `max`, the shape kept, never made bigger.
 * 4032×3024 -> 1280×960; 3024×4032 -> 960×1280; 800×600 -> 800×600. */
export function shrunkSize(width: number, height: number, max = MAX_EDGE): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= max) return { width, height };
  const scale = max / longest;
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** Whether a picked file is worth shrinking before it goes: a big photo -> true; a 200 KB picture, or a file that
 * isn't a picture -> false (it goes as it is). */
export function worthShrinking(file: { size: number; type: string }): boolean {
  return file.type.startsWith("image/") && file.size > SMALL_ENOUGH;
}

/** The photo as a JPEG at most MAX_EDGE on its long edge, or the original file when it's small or can't be shrunk
 * here (an old browser, a format it can't draw): the server shrinks those as before. The browser turns the picture
 * upright from its camera tag as it draws it, so the shrunk copy needs no tag. */
export async function shrinkPhoto(file: File): Promise<Blob> {
  if (!worthShrinking(file)) return file;
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const size = shrunkSize(img.naturalWidth, img.naturalHeight);
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const pen = canvas.getContext("2d");
    if (!pen) return file;
    pen.drawImage(img, 0, 0, size.width, size.height);
    const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/jpeg", QUALITY));
    if (!blob) return file;
    return blob;
  } catch {
    return file;
  } finally {
    URL.revokeObjectURL(url);
  }
}
