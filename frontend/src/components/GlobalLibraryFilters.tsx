import type { GlobalLibraryFilters as FilterOptions } from "../types/analysis";

export type GlobalLibraryFilterState = {
  query: string;
  package_name: string;
  category: string;
  confidence: string;
  sort: string;
};

type Props = {
  filters: GlobalLibraryFilterState;
  options?: FilterOptions;
  onChange: (filters: GlobalLibraryFilterState) => void;
  onSubmit: () => void;
  onReset: () => void;
};

export function GlobalLibraryFilters({ filters, options, onChange, onSubmit, onReset }: Props) {
  function update(key: keyof GlobalLibraryFilterState, value: string) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <form
      className="filter-bar"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <input
        aria-label="搜索全局函数库"
        placeholder="搜索 torch.randn / Linear / numpy..."
        value={filters.query}
        onChange={(event) => update("query", event.target.value)}
      />
      <select aria-label="按包筛选" value={filters.package_name} onChange={(event) => update("package_name", event.target.value)}>
        <option value="">全部 package</option>
        {(options?.packages ?? []).map((item) => (
          <option value={item} key={item}>{item}</option>
        ))}
      </select>
      <select aria-label="按类别筛选" value={filters.category} onChange={(event) => update("category", event.target.value)}>
        <option value="">全部 category</option>
        {(options?.categories ?? []).map((item) => (
          <option value={item} key={item}>{item}</option>
        ))}
      </select>
      <select aria-label="按置信度筛选" value={filters.confidence} onChange={(event) => update("confidence", event.target.value)}>
        <option value="">全部 confidence</option>
        {(options?.confidences ?? []).map((item) => (
          <option value={item} key={item}>{item}</option>
        ))}
      </select>
      <select aria-label="排序" value={filters.sort} onChange={(event) => update("sort", event.target.value)}>
        <option value="canonical_name">函数名</option>
        <option value="updated_at">最近更新</option>
        <option value="occurrence_count">出现次数</option>
      </select>
      <button className="primary-button" type="submit">搜索</button>
      <button className="secondary-button" type="button" onClick={onReset}>清空筛选</button>
    </form>
  );
}
