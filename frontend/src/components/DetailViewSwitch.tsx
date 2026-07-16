import { useState } from "react";
import type { ReactNode } from "react";

type View = "basic" | "ai";

type Props = {
  basic: ReactNode;
  ai?: ReactNode;
  aiAvailable?: boolean;
};

export function DetailViewSwitch({ basic, ai, aiAvailable = false }: Props) {
  const [view, setView] = useState<View>("basic");
  const canShowAi = Boolean(aiAvailable && ai);
  const activeView = view === "ai" && canShowAi ? "ai" : "basic";
  return (
    <div className="detail-switch">
      <div className="segmented detail-segmented" aria-label="解释视图">
        <button className={activeView === "basic" ? "active" : ""} onClick={() => setView("basic")} type="button">
          基础解释
        </button>
        <button className={activeView === "ai" ? "active" : ""} disabled={!canShowAi} onClick={() => setView("ai")} type="button">
          AI 解释
        </button>
      </div>
      <div className="detail-pane">{activeView === "ai" ? ai : basic}</div>
    </div>
  );
}
