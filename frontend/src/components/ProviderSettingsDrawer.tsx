import { CheckCircle2, KeyRound, Loader2, PlugZap, RefreshCw, Save, Settings2, Trash2, X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  deleteProviderApiKey,
  getProviderSettings,
  saveProviderSettings,
  testProviderSettings,
  validateProviderSettings
} from "../api/client";
import { notifyProviderSettingsUpdated } from "../providerSettingsEvents";
import type { ProviderPublicSettings, ProviderSettingsPayload } from "../types/analysis";

type Props = {
  open: boolean;
  onClose: () => void;
};

type Draft = {
  enabled: boolean;
  api_key: string;
  base_url: string;
  model: string;
  timeout_seconds: string;
  retry: string;
  max_output_tokens: string;
  request_width: string;
  request_height: string;
  allowed_domains: string;
  endpoint_path: string;
  workspace: string;
  supports_async: boolean;
  supports_json_object: boolean;
  disable_thinking: boolean;
  allow_custom_base_url: boolean;
  allow_local_endpoint: boolean;
};

const GROUPS = [
  ["text_llm", "文本 LLM"],
  ["vision_vlm", "视觉 VLM"],
  ["image_generation", "图片生成"]
] as const;

export function ProviderSettingsDrawer({ open, onClose }: Props) {
  const [providers, setProviders] = useState<ProviderPublicSettings[]>([]);
  const [selectedId, setSelectedId] = useState<string>("deepseek");
  const [draft, setDraft] = useState<Draft>(() => emptyDraft());
  const [activeGroup, setActiveGroup] = useState<(typeof GROUPS)[number][0]>("text_llm");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(() => providers.find((item) => item.id === selectedId) ?? providers[0], [providers, selectedId]);
  const visibleProviders = providers.filter((item) => item.group === activeGroup);

  useEffect(() => {
    if (open) {
      void reload();
    }
  }, [open]);

  useEffect(() => {
    if (selected) {
      setDraft(draftFromProvider(selected));
    }
  }, [selected?.id, selected?.revision]);

  async function reload() {
    setBusy(true);
    setError(null);
    try {
      const response = await getProviderSettings();
      setProviders(response.providers);
      const current = response.providers.find((item) => item.id === selectedId) ?? response.providers[0];
      if (current) {
        setSelectedId(current.id);
        setActiveGroup(current.group);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载 Provider 设置失败");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const payload = payloadFromDraft(draft, selected.revision, selected.group);
      await saveProviderSettings(selected.id, payload);
      setDraft((current) => ({ ...current, api_key: "" }));
      setStatus("已保存");
      await reload();
      notifyProviderSettingsUpdated();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const response = await validateProviderSettings(selected.id, payloadFromDraft(draft, selected.revision, selected.group));
      if (!response.ok) {
        setError(response.errors.join("；") || "校验未通过");
        return;
      }
      const warningText = response.warnings.length ? `；${response.warnings.join("；")}` : "";
      setStatus(`本地配置校验通过${warningText}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "校验失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeKey() {
    if (!selected) return;
    if (selected.api_key_source === "Environment") {
      setStatus(null);
      setError("环境变量 Key 不能从 UI 删除。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteProviderApiKey(selected.id, selected.revision);
      setStatus("UI Key 已清除");
      await reload();
      notifyProviderSettingsUpdated();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    if (!selected) return;
    if (!window.confirm("Provider test may send one minimal paid request.")) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const response = await testProviderSettings(selected.id, true);
      setStatus(response.success ? `连接成功 ${response.latency_ms ?? 0}ms` : `连接失败：${response.warning ?? "unknown"}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "连接测试失败");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="drawer-backdrop" role="presentation">
      <aside className="settings-drawer" role="dialog" aria-modal="true" aria-label="Provider 设置中心">
        <header className="drawer-header">
          <div className="drawer-title">
            <Settings2 aria-hidden="true" size={22} />
            <div>
              <h2>Provider 设置</h2>
              <span>字段来源与安全连接</span>
            </div>
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label="关闭设置">
            <X aria-hidden="true" size={18} />
          </button>
        </header>

        <div className="provider-layout">
          <nav className="provider-nav" aria-label="Provider 分组">
            <div className="segmented">
              {GROUPS.map(([group, label]) => (
                <button key={group} className={activeGroup === group ? "active" : ""} onClick={() => setActiveGroup(group)} type="button">
                  {label}
                </button>
              ))}
            </div>
            <div className="provider-list">
              {visibleProviders.map((provider) => (
                <button
                  key={provider.id}
                  className={provider.id === selected?.id ? "provider-button active" : "provider-button"}
                  onClick={() => setSelectedId(provider.id)}
                  type="button"
                >
                  <span>{provider.display_name}</span>
                  <small>{provider.configured ? "configured" : "not configured"}</small>
                </button>
              ))}
            </div>
          </nav>

          <div className="provider-form-shell">
            {busy && <p className="inline-status"><Loader2 aria-hidden="true" size={16} /> 处理中...</p>}
            {error && <p className="inline-error">{error}</p>}
            {status && <p className="inline-status"><CheckCircle2 aria-hidden="true" size={16} /> {status}</p>}
            {selected && (
              <ProviderSettingsForm
                provider={selected}
                draft={draft}
                onDraftChange={setDraft}
                onSave={save}
                onValidate={validate}
                onDeleteKey={removeKey}
                onTest={runTest}
                disabled={busy}
              />
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

function ProviderSettingsForm({
  provider,
  draft,
  onDraftChange,
  onSave,
  onValidate,
  onDeleteKey,
  onTest,
  disabled
}: {
  provider: ProviderPublicSettings;
  draft: Draft;
  onDraftChange: (draft: Draft) => void;
  onSave: () => void;
  onValidate: () => void;
  onDeleteKey: () => void;
  onTest: () => void;
  disabled: boolean;
}) {
  const isImage = provider.group === "image_generation";
  const isVision = provider.group === "vision_vlm";
  return (
    <form className="provider-form" onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <div className="provider-form-header">
        <div>
          <h3>{provider.display_name}</h3>
          <p>{provider.id}</p>
        </div>
        <label className="switch-label">
          <input checked={draft.enabled} onChange={(event) => onDraftChange({ ...draft, enabled: event.target.checked })} type="checkbox" />
          <span>Enabled</span>
        </label>
      </div>

      <div className="field-grid">
        <Field label="API Key" source={provider.api_key_source === "None" ? undefined : provider.api_key_source}>
          <input
            autoComplete="off"
            placeholder={provider.configured ? provider.masked_key ?? "configured" : ""}
            type="password"
            value={draft.api_key}
            onChange={(event) => onDraftChange({ ...draft, api_key: event.target.value })}
          />
        </Field>
        <Field label="Base URL" source={provider.source.base_url}>
          <input value={draft.base_url} onChange={(event) => onDraftChange({ ...draft, base_url: event.target.value })} />
        </Field>
        <Field label="Model" source={provider.source.model}>
          <input value={draft.model} onChange={(event) => onDraftChange({ ...draft, model: event.target.value })} />
        </Field>
        <Field label="Timeout" source={provider.source.timeout_seconds}>
          <input inputMode="decimal" value={draft.timeout_seconds} onChange={(event) => onDraftChange({ ...draft, timeout_seconds: event.target.value })} />
        </Field>
        <Field label="Retry" source={provider.source.retry}>
          <input inputMode="numeric" value={draft.retry} onChange={(event) => onDraftChange({ ...draft, retry: event.target.value })} />
        </Field>
        {!isImage && (
          <Field label="Max Output Tokens" source={provider.source.max_output_tokens}>
            <input inputMode="numeric" value={draft.max_output_tokens} onChange={(event) => onDraftChange({ ...draft, max_output_tokens: event.target.value })} />
          </Field>
        )}
        {isImage && (
          <>
            <Field label="Width" source={provider.source.request_width}>
              <input inputMode="numeric" value={draft.request_width} onChange={(event) => onDraftChange({ ...draft, request_width: event.target.value })} />
            </Field>
            <Field label="Height" source={provider.source.request_height}>
              <input inputMode="numeric" value={draft.request_height} onChange={(event) => onDraftChange({ ...draft, request_height: event.target.value })} />
            </Field>
            <Field label="Endpoint Path" source={provider.source.endpoint_path}>
              <input value={draft.endpoint_path} onChange={(event) => onDraftChange({ ...draft, endpoint_path: event.target.value })} />
            </Field>
            <Field label="Workspace" source={provider.source.workspace}>
              <input value={draft.workspace} onChange={(event) => onDraftChange({ ...draft, workspace: event.target.value })} />
            </Field>
            <Field label="Allowlist" source={provider.source.allowed_domains}>
              <TagInput value={draft.allowed_domains} onChange={(allowed_domains) => onDraftChange({ ...draft, allowed_domains })} />
            </Field>
          </>
        )}
        {isVision && (
          <>
            <label className="checkbox-label compact">
              <input checked={draft.supports_json_object} onChange={(event) => onDraftChange({ ...draft, supports_json_object: event.target.checked })} type="checkbox" />
              JSON object
            </label>
            <label className="checkbox-label compact">
              <input checked={draft.disable_thinking} onChange={(event) => onDraftChange({ ...draft, disable_thinking: event.target.checked })} type="checkbox" />
              Disable thinking
            </label>
          </>
        )}
      </div>

      <div className="advanced-row">
        <label className="checkbox-label compact">
          <input checked={draft.allow_custom_base_url} onChange={(event) => onDraftChange({ ...draft, allow_custom_base_url: event.target.checked })} type="checkbox" />
          Custom endpoint
        </label>
        <label className="checkbox-label compact">
          <input checked={draft.allow_local_endpoint} onChange={(event) => onDraftChange({ ...draft, allow_local_endpoint: event.target.checked })} type="checkbox" />
          Local endpoint
        </label>
      </div>

      {provider.warnings?.map((warning) => <p className="inline-warning" key={warning}>{warning}</p>)}
      {provider.api_key_source === "Environment" && <p className="inline-note">环境变量 Key 不能从 UI 删除。</p>}

      <div className="drawer-actions">
        <button className="primary-button" disabled={disabled} type="submit">
          <Save aria-hidden="true" size={16} /> 保存
        </button>
        <button className="secondary-button" disabled={disabled} onClick={onValidate} type="button">
          <PlugZap aria-hidden="true" size={16} /> 校验
        </button>
        <button className="secondary-button" disabled={disabled || !provider.configured} onClick={onTest} type="button">
          <RefreshCw aria-hidden="true" size={16} /> Test
        </button>
        <button className="danger-button" disabled={disabled || !provider.configured || provider.api_key_source === "Environment"} onClick={onDeleteKey} type="button">
          <Trash2 aria-hidden="true" size={16} /> 删除 Key
        </button>
      </div>
      <p className="key-state"><KeyRound aria-hidden="true" size={14} /> {provider.configured ? "configured" : "not configured"}</p>
    </form>
  );
}

function Field({ label, source, children }: { label: string; source?: string; children: ReactNode }) {
  return (
    <label>
      <span className="field-label">
        {label}
        {source && <small className={`source-badge ${source.toLowerCase()}`}>{source}</small>}
      </span>
      {children}
    </label>
  );
}

function TagInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [draft, setDraft] = useState("");
  const tags = value.split(",").map((item) => item.trim()).filter(Boolean);

  function commit(raw: string) {
    const next = raw.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
    if (!next.length) return;
    const merged = Array.from(new Set([...tags, ...next]));
    onChange(merged.join(","));
    setDraft("");
  }

  function remove(tag: string) {
    onChange(tags.filter((item) => item !== tag).join(","));
  }

  return (
    <div className="tag-input">
      <div className="tag-list" aria-label="Allowed result domains">
        {tags.map((tag) => (
          <button key={tag} className="tag-chip" type="button" onClick={() => remove(tag)} title="移除域名">
            {tag}
          </button>
        ))}
      </div>
      <input
        value={draft}
        placeholder="输入域名后回车"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => commit(draft)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            commit(draft);
          }
          if (event.key === "Backspace" && !draft && tags.length) {
            remove(tags[tags.length - 1]);
          }
        }}
      />
    </div>
  );
}

function emptyDraft(): Draft {
  return {
    enabled: true,
    api_key: "",
    base_url: "",
    model: "",
    timeout_seconds: "",
    retry: "",
    max_output_tokens: "",
    request_width: "",
    request_height: "",
    allowed_domains: "",
    endpoint_path: "",
    workspace: "",
    supports_async: false,
    supports_json_object: false,
    disable_thinking: false,
    allow_custom_base_url: false,
    allow_local_endpoint: false
  };
}

function draftFromProvider(provider: ProviderPublicSettings): Draft {
  const fields = provider.fields;
  return {
    ...emptyDraft(),
    enabled: Boolean(provider.enabled),
    base_url: String(fields.base_url ?? ""),
    model: String(fields.model ?? ""),
    timeout_seconds: String(fields.timeout_seconds ?? ""),
    retry: String(fields.retry ?? ""),
    max_output_tokens: String(fields.max_output_tokens ?? ""),
    request_width: String(fields.request_width ?? ""),
    request_height: String(fields.request_height ?? ""),
    allowed_domains: Array.isArray(fields.allowed_domains) ? fields.allowed_domains.join(",") : String(fields.allowed_domains ?? ""),
    endpoint_path: String(fields.endpoint_path ?? ""),
    workspace: String(fields.workspace ?? ""),
    supports_async: Boolean(fields.supports_async),
    supports_json_object: Boolean(fields.supports_json_object),
    disable_thinking: Boolean(fields.disable_thinking),
    allow_custom_base_url: Boolean(fields.allow_custom_base_url),
    allow_local_endpoint: Boolean(fields.allow_local_endpoint)
  };
}

function payloadFromDraft(
  draft: Draft,
  expected_revision: number,
  group: ProviderPublicSettings["group"]
): ProviderSettingsPayload {
  const payload: ProviderSettingsPayload = {
    expected_revision,
    enabled: draft.enabled,
    base_url: draft.base_url.trim(),
    model: draft.model.trim(),
    timeout_seconds: numberOrUndefined(draft.timeout_seconds),
    retry: numberOrUndefined(draft.retry),
    max_output_tokens: numberOrUndefined(draft.max_output_tokens),
    request_width: numberOrUndefined(draft.request_width),
    request_height: numberOrUndefined(draft.request_height),
    endpoint_path: draft.endpoint_path.trim() || undefined,
    workspace: draft.workspace.trim() || undefined,
    supports_async: group === "image_generation" ? false : draft.supports_async,
    supports_json_object: draft.supports_json_object,
    disable_thinking: draft.disable_thinking,
    allow_custom_base_url: draft.allow_custom_base_url,
    allow_local_endpoint: draft.allow_local_endpoint
  };
  const key = draft.api_key.trim();
  if (key) payload.api_key = key;
  const domains = draft.allowed_domains.split(",").map((item) => item.trim()).filter(Boolean);
  if (group === "image_generation" || domains.length) payload.allowed_domains = domains;
  return payload;
}

function numberOrUndefined(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}
