import type { Mode } from "../types/analysis";

type Props = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
};

export function ModeToggle({ mode, onModeChange }: Props) {
  return (
    <div className="mode-toggle" aria-label="阅读模式">
      <button className={mode === "normal" ? "active" : ""} onClick={() => onModeChange("normal")}>
        正常模式
      </button>
      <button className={mode === "beginner" ? "active" : ""} onClick={() => onModeChange("beginner")}>
        零基础模式
      </button>
    </div>
  );
}
