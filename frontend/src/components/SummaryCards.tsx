import type { AnalysisResult } from "../types/analysis";
import { DashboardOverview } from "./DashboardOverview";

export function SummaryCards({ result }: { result: AnalysisResult }) {
  return <DashboardOverview result={result} />;
}
