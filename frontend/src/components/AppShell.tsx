import type { ReactNode } from "react";
import type { Mode } from "../types/analysis";
import { ModeToggle } from "./ModeToggle";

type Props = {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  children: ReactNode;
};

export function AppShell({ mode, onModeChange, children }: Props) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CR</span>
          <span>CodeResearch Agent</span>
        </div>
        <ModeToggle mode={mode} onModeChange={onModeChange} />
      </header>
      {children}
    </div>
  );
}
