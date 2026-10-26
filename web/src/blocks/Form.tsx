import { useContext, useState } from "react";
import { ChatActions } from "./ChatActions";
import { formatWithUnit } from "./fenceValues";
import { answerMessage, canSend, sentTime, startingValues, type FormValue, type FormValues } from "./formAnswer";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import { TEXT_VALUE, type FormBlock, type FormField, type FormOption } from "./parse/form";

type Sent = { at: number } | null;
type ViewProps = {
  form: FormBlock; values: FormValues; sent: Sent; ready: boolean;
  onChange: (id: string, value: FormValue) => void; onSend: () => void;
};

/** A form in a reply: the user changes the model's prefilled answers and presses Send. Sending is an ordinary user
 *  message (the same send the reply's buttons use): a line for the bubble and an odie-form-answer block the model
 *  reads by field id. A form is sent once; then it turns grey with the choices still showing and "✓ Sent 15:42". */
export function Form(form: FormBlock) {
  const { send, busy } = useContext(ChatActions);
  const [values, setValues] = useState<FormValues>(() => startingValues(form));
  const [sent, setSent] = useState<Sent>(null);
  const ready = canSend(form, values, busy, sent !== null);
  function onSend() {
    if (!ready) return;
    setSent({ at: Date.now() });
    send(answerMessage(form, values));
  }
  return <FormView form={form} values={values} sent={sent} ready={ready} onChange={(id, v) => setValues((all) => ({ ...all, [id]: v }))} onSend={onSend} />;
}

/** The form as drawn for these values: live, or grey and still once sent. */
export function FormView({ form, values, sent, ready, onChange, onSend }: ViewProps) {
  const inCard = useContext(InCard);
  const frame = inCard ? "my-2" : "glass glass-solid rounded-[20px] px-4 py-3 my-2";
  const answered = sent !== null;
  return (
    <form className={`${frame} ${answered ? "opacity-60 grayscale" : ""}`} aria-disabled={answered}
      onSubmit={(e) => { e.preventDefault(); onSend(); }}>
      {form.title && <div className="text-[15px] leading-[21px] font-bold"><InlineText text={form.title} /></div>}
      <fieldset disabled={answered} className="min-w-0 border-0 p-0 m-0">
        {form.fields.map((field, i) => (
          <div key={field.id}>
            {startsGroup(form.fields, i) && <div className="pt-3 pb-0.5 text-[12px] font-bold text-muted"><InlineText text={field.group!} /></div>}
            <FieldView field={field} value={values[field.id]} onChange={(v) => onChange(field.id, v)} />
          </div>
        ))}
      </fieldset>
      <div className="flex items-center justify-end gap-3 mt-3">
        {answered && <span className="flex-1 text-[12.5px] font-semibold text-muted">✓ Sent {sentTime(sent.at)}</span>}
        <button type="submit" disabled={!ready} className="pill pill-solid h-11 px-5 text-[14.5px] shadow-none disabled:opacity-40">{form.submit}</button>
      </div>
    </form>
  );
}

/** Whether field i starts a new group heading: it has a group, and the field before it has a different one (or none).
 *  [Narrator (Cast), Keeper (Cast), Length]: at 0 → yes, at 1 → no, at 2 → no */
function startsGroup(fields: FormField[], i: number): boolean {
  const group = fields[i].group;
  if (!group) return false;
  return fields[i - 1]?.group !== group;
}

function FieldView({ field, value, onChange }: { field: FormField; value: FormValue | undefined; onChange: (v: FormValue) => void }) {
  const labelClass = "block text-[13.5px] font-semibold text-ink-2";
  const inputClass = "w-full min-w-0 rounded-[12px] border border-line bg-surface px-3 text-[15px] text-ink";
  if (field.kind === "slider") return <SliderView field={field} value={Number(value ?? field.value)} onChange={onChange} />;
  if (field.kind === "text") {
    const text = String(value ?? "");
    return (
      <label className="block py-2">
        <span className={labelClass}><InlineText text={field.label} /></span>
        {field.multiline
          ? <textarea value={text} rows={3} maxLength={TEXT_VALUE} placeholder={field.placeholder} onChange={(e) => onChange(e.target.value)} className={`${inputClass} mt-1.5 py-2.5 resize-y`} />
          : <input type="text" value={text} maxLength={TEXT_VALUE} placeholder={field.placeholder} onChange={(e) => onChange(e.target.value)} className={`${inputClass} mt-1.5 h-11`} />}
      </label>
    );
  }
  if (field.kind === "select") {
    const chosen = field.options.find((o) => o.value === value);
    return (
      <label className="block py-2">
        <span className={labelClass}><InlineText text={field.label} /></span>
        <span className="flex items-center gap-2 mt-1.5">
          <select value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} className={`${inputClass} h-11 flex-1`}>
            {!chosen && <option value="" disabled>Choose…</option>}
            {field.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {chosen?.preview && <PreviewButton url={chosen.preview} label={chosen.label} />}
        </span>
        {chosen?.note && <span className="block text-[12px] leading-4 text-dim mt-1">{chosen.note}</span>}
      </label>
    );
  }
  const picked = field.kind === "checkbox" ? (Array.isArray(value) ? value : []) : [String(value ?? "")];
  const isRadio = field.kind === "radio";
  const optionValues = field.options.map((o) => o.value);
  function tap(option: FormOption) {
    if (isRadio) return onChange(option.value);
    const ticked = picked.includes(option.value) ? picked.filter((v) => v !== option.value) : [...picked, option.value];
    onChange(optionValues.filter((v) => ticked.includes(v)));  // kept in the options' order
  }
  return (
    <div className="py-2" role={field.kind === "radio" ? "radiogroup" : "group"} aria-label={field.label}>
      <span className={labelClass}><InlineText text={field.label} /></span>
      <div className="flex flex-wrap gap-2 mt-1.5">
        {field.options.map((o) => (
          <OptionPill key={o.value} option={o} role={field.kind === "radio" ? "radio" : "checkbox"} on={picked.includes(o.value)} onTap={() => tap(o)} />
        ))}
      </div>
    </div>
  );
}

/** One radio or checkbox option: a pill in the app's ember accent when chosen, its note under its label, and a ▶ when
 *  it has a voice preview. */
function OptionPill({ option, role, on, onTap }: { option: FormOption; role: "radio" | "checkbox"; on: boolean; onTap: () => void }) {
  const look = on ? "border-ember-text bg-ember-tint text-ember-text font-semibold" : "border-line text-ink";
  return (
    <span className="inline-flex items-center gap-0.5 max-w-full">
      <button type="button" role={role} aria-checked={on} onClick={onTap}
        className={`min-h-10 max-w-full rounded-[14px] border px-3.5 py-1.5 text-left text-[14px] leading-[18px] ${look}`}>
        <span className="block">{option.label}</span>
        {option.note && <span className="block text-[11.5px] leading-[15px] font-normal text-dim">{option.note}</span>}
      </button>
      {option.preview && <PreviewButton url={option.preview} label={option.label} />}
    </span>
  );
}

function SliderView({ field, value, onChange }: { field: Extract<FormField, { kind: "slider" }>; value: number; onChange: (v: number) => void }) {
  const share = (value - field.min) / (field.max - field.min);
  const fill = { "--fill": `${share * 100}%` } as React.CSSProperties;
  return (
    <label className="block py-2">
      <span className="flex items-baseline gap-2">
        <span className="flex-1 min-w-0 text-[13.5px] font-semibold text-ink-2"><InlineText text={field.label} /></span>
        <span className="text-[15px] font-bold tabular-nums whitespace-nowrap">{formatWithUnit(value, field.unit)}</span>
      </span>
      <input type="range" className="slider mt-2" style={fill} min={field.min} max={field.max} step={field.step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
      {field.ends && (
        <span className="flex justify-between text-[11px] text-dim mt-0.5"><span>{field.ends[0]}</span><span>{field.ends[1]}</span></span>
      )}
    </label>
  );
}

// One preview plays at a time, across every form on the screen.
let playing: HTMLAudioElement | null = null;

/** ▶ for an option's voice preview (a path to Odie's own previews, checked by the reader); ■ while it plays. */
function PreviewButton({ url, label }: { url: string; label: string }) {
  const [on, setOn] = useState(false);
  function toggle() {
    if (on) { playing?.pause(); setOn(false); return; }
    playing?.pause();
    const audio = new Audio(url);
    playing = audio;
    audio.onended = () => setOn(false);
    audio.onerror = () => setOn(false);
    setOn(true);
    void audio.play().catch(() => setOn(false));
  }
  return (
    <button type="button" onClick={toggle} aria-label={on ? `Stop ${label}` : `Hear ${label}`} className="w-10 h-10 shrink-0 rounded-full grid place-items-center text-muted">
      {on ? <span className="w-3 h-3 rounded-[2px] bg-current" /> : <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>}
    </button>
  );
}
