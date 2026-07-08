import type { LibraryCall } from "../types/analysis";

type Props = {
  call: LibraryCall;
  onClick: (call: LibraryCall) => void;
};

export function LibraryCallChip({ call, onClick }: Props) {
  const name = call.canonical_name || call.display_name || call.call_text || "unknown";
  const isWeak = call.confidence === "low" || call.category === "unknown";
  return (
    <button className={`chip ${isWeak ? "low" : ""}`} onClick={() => onClick(call)} type="button">
      {name}
      {call.line_no ? ` :${call.line_no}` : ""}
    </button>
  );
}
