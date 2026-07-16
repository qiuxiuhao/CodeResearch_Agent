import type { FunctionAnalysis, LibraryCall, LLMExplanation, Mode } from "../types/analysis";
import { LibraryCallChip } from "./LibraryCallChip";
import { AIExplanationCard } from "./AIExplanationCard";
import { DetailViewSwitch } from "./DetailViewSwitch";

type Props = {
  fn: FunctionAnalysis;
  mode: Mode;
  onLibraryCallClick: (call: LibraryCall) => void;
  explanation?: LLMExplanation;
};

export function FunctionDetail({ fn, mode, explanation, onLibraryCallClick }: Props) {
  const calls = fn.library_calls ?? [];
  return (
    <article className="item-card">
      <h3>{fn.qualified_name || fn.function_name}</h3>
      <DetailViewSwitch
        aiAvailable={Boolean(explanation)}
        ai={<AIExplanationCard explanation={explanation} mode={mode} />}
        basic={
          <>
            <p>{fn.purpose}</p>
            <p>输入：{(fn.inputs ?? []).join(", ") || "无"}</p>
            <p>输出：{(fn.outputs ?? []).join(", ") || "无"}</p>
            {fn.is_core_function && <p className="muted">核心函数：{fn.core_reason || "是"}</p>}

            {mode === "beginner" && fn.beginner_explanation && (
              <section>
                <h4>零基础解释</h4>
                <p>{fn.beginner_explanation}</p>
              </section>
            )}

            <section>
              <h4>实现逻辑</h4>
              {(fn.implementation_logic ?? []).length > 0 ? (
                <ol>
                  {(fn.implementation_logic ?? []).map((step, index) => (
                    <li key={`${step}-${index}`}>{step}</li>
                  ))}
                </ol>
              ) : (
                <p className="muted">暂无实现逻辑。</p>
              )}
            </section>

            <section>
              <h4>{mode === "beginner" ? "本函数调用的库函数" : "库函数调用"}</h4>
              {calls.length > 0 ? (
                <div className="chip-row">
                  {calls.map((call, index) => (
                    <LibraryCallChip key={`${call.canonical_name}-${call.line_no}-${index}`} call={call} onClick={onLibraryCallClick} />
                  ))}
                </div>
              ) : (
                <p className="muted">无库函数调用。</p>
              )}
            </section>
          </>
        }
      />
    </article>
  );
}
