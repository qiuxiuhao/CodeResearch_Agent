import { useEffect, useId, useState } from "react";

const MERMAID_CONFIG = {
  startOnLoad: false,
  securityLevel: "strict" as const,
  theme: "base" as const,
  themeVariables: {
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
    fontSize: "18px",
    primaryTextColor: "#111827",
    lineColor: "#334155",
    primaryBorderColor: "#8b5cf6",
    primaryColor: "#eef2ff"
  }
};

export function MermaidBlock({ code }: { code: string }) {
  const id = useId().replace(/:/g, "_");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      try {
        const { default: mermaid } = await import("mermaid");
        if (cancelled) return;
        mermaid.initialize(MERMAID_CONFIG);
        if (cancelled) return;
        const rendered = await mermaid.render(`diagram_${id}`, code);
        if (cancelled) return;
        setSvg(rendered.svg);
        setError(null);
      } catch (exc) {
        if (cancelled) return;
        setSvg(null);
        setError(exc instanceof Error ? exc.message : "Mermaid 渲染失败");
      }
    }
    if (code) {
      void render();
    }
    return () => {
      cancelled = true;
    };
  }, [code, id]);

  if (svg) {
    return <div className="mermaid-rendered" dangerouslySetInnerHTML={{ __html: svg }} />;
  }
  return (
    <div>
      {error && <p className="muted">Mermaid 渲染失败，已回退到源码展示。</p>}
      <pre className="code-block">{code}</pre>
    </div>
  );
}
