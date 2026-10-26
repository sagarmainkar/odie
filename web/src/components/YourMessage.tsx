import { withoutFormAnswers } from "../blocks/formAnswer";
import { CopyButton } from "./CopyButton";

/** A message you sent: its photos, its words in your bubble, and under the bubble the same copy button Odie's replies
 * have (a tick for "Copied"). The text is what you typed: the server strips what Odie appended before it comes back.
 * A form's answer shows as its line only: the odie-form-answer block after it is for the model. */
export function YourMessage({ text: sent, images }: { text: string; images?: string[] }) {
  const text = withoutFormAnswers(sent);
  const hasPhotos = !!images && images.length > 0;
  return (
    <div className="ml-auto max-w-[80%] w-fit flex flex-col items-end gap-0.5">
      {hasPhotos && (
        <div className="flex gap-0.5 justify-end flex-wrap mb-1">
          {images.map((id) => <img key={id} src={`/api/uploads/${id}`} alt="" className="w-[140px] h-[140px] object-cover rounded-[18px]" />)}
        </div>
      )}
      {text && (
        <>
          <div className="bubble-me rounded-[24px] rounded-br-[8px] px-4 py-3 text-[15.5px] leading-[1.5] whitespace-pre-wrap break-words">{text}</div>
          <div className="flex items-center mr-1 text-muted"><CopyButton text={text} label="Copy message" /></div>
        </>
      )}
    </div>
  );
}
