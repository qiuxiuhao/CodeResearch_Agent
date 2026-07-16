import type { ReactNode } from "react";
import { Settings } from "lucide-react";
import type { Mode } from "../types/analysis";
import { ModeToggle } from "./ModeToggle";

type Props = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenSettings: () => void;
  children: ReactNode;
};

export function AppShell({ mode, onModeChange, onOpenSettings, children }: Props) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CR</span>
          <span>CodeResearch Agent</span>
        </div>
        <div className="topbar-actions">
          <ModeToggle mode={mode} onModeChange={onModeChange} />
          <button className="icon-button" onClick={onOpenSettings} type="button" aria-label="打开 Provider 设置">
            <Settings aria-hidden="true" size={18} />
          </button>
        </div>
      </header>
      {children}
    </div>
  );
}
