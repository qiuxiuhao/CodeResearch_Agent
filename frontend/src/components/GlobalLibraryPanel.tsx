import { useEffect, useState } from "react";
import {
  getGlobalLibraryFunction,
  getGlobalLibraryStats,
  getLowConfidenceFunctions,
  listGlobalLibraryFunctions
} from "../api/client";
import type {
  GlobalLibraryDetailResponse,
  GlobalLibraryFunction,
  GlobalLibraryListResponse,
  GlobalLibraryStats
} from "../types/analysis";
import { EmptyState } from "./EmptyState";
import { ErrorBanner } from "./ErrorBanner";
import { GlobalLibraryDetail } from "./GlobalLibraryDetail";
import { GlobalLibraryFilters, type GlobalLibraryFilterState } from "./GlobalLibraryFilters";
import { GlobalLibraryList } from "./GlobalLibraryList";
import { LoadingState } from "./LoadingState";
import { LowConfidenceFunctions } from "./LowConfidenceFunctions";

const DEFAULT_FILTERS: GlobalLibraryFilterState = {
  query: "",
  package_name: "",
  category: "",
  confidence: "",
  sort: "canonical_name"
};

export function GlobalLibraryPanel() {
  const [filters, setFilters] = useState<GlobalLibraryFilterState>(DEFAULT_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<GlobalLibraryFilterState>(DEFAULT_FILTERS);
  const [listResponse, setListResponse] = useState<GlobalLibraryListResponse | null>(null);
  const [stats, setStats] = useState<GlobalLibraryStats | null>(null);
  const [lowConfidence, setLowConfidence] = useState<GlobalLibraryFunction[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [detail, setDetail] = useState<GlobalLibraryDetailResponse | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadOverview();
  }, []);

  useEffect(() => {
    void loadList(appliedFilters);
  }, [appliedFilters]);

  async function loadOverview() {
    setError(null);
    try {
      const [nextStats, nextLow] = await Promise.all([
        getGlobalLibraryStats(),
        getLowConfidenceFunctions(10)
      ]);
      setStats(nextStats);
      setLowConfidence(nextLow.items);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载全局函数库概览失败");
    }
  }

  async function loadList(nextFilters: GlobalLibraryFilterState) {
    setIsLoadingList(true);
    setError(null);
    try {
      const response = await listGlobalLibraryFunctions({
        ...nextFilters,
        limit: 50,
        offset: 0
      });
      setListResponse(response);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载全局函数库失败");
    } finally {
      setIsLoadingList(false);
    }
  }

  async function selectFunction(canonicalName: string) {
    setSelectedName(canonicalName);
    setIsLoadingDetail(true);
    setError(null);
    try {
      const nextDetail = await getGlobalLibraryFunction(canonicalName);
      setDetail(nextDetail);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载函数详情失败");
      setDetail(null);
    } finally {
      setIsLoadingDetail(false);
    }
  }

  function submitFilters() {
    setAppliedFilters(filters);
  }

  function resetFilters() {
    setFilters(DEFAULT_FILTERS);
    setAppliedFilters(DEFAULT_FILTERS);
  }

  const items = listResponse?.items ?? [];
  return (
    <section className="tab-content">
      <h2>全局函数库</h2>
      <p className="muted">查看分析任务沉淀下来的 Python / PyTorch / NumPy 等库函数教学说明。</p>
      {error && <ErrorBanner message={error} />}
      {stats ? (
        <div className="summary-grid">
          <Metric label="函数数" value={stats.function_count} />
          <Metric label="包数量" value={stats.package_counts.length} />
          <Metric label="类别数量" value={stats.category_counts.length} />
        </div>
      ) : (
        <EmptyState message="暂无全局函数库统计。" />
      )}
      <GlobalLibraryFilters
        filters={filters}
        options={listResponse?.filters}
        onChange={setFilters}
        onSubmit={submitFilters}
        onReset={resetFilters}
      />
      <div className="library-layout">
        <div>
          <h3>函数列表</h3>
          {isLoadingList ? (
            <LoadingState message="正在加载全局函数库..." />
          ) : (
            <>
              <p className="muted">共 {listResponse?.total ?? 0} 个匹配结果</p>
              <GlobalLibraryList items={items} selectedName={selectedName} onSelect={selectFunction} />
            </>
          )}
        </div>
        <aside>
          <LowConfidenceFunctions items={lowConfidence} onSelect={selectFunction} />
        </aside>
      </div>
      <h3>函数详情</h3>
      <GlobalLibraryDetail detail={detail} isLoading={isLoadingDetail} />
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
