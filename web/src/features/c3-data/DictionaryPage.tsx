/** Data Dictionary (/ops/dictionary): entities grouped by owner component, generate, export. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getToken } from "../../api/http";
import {
  type DictEntity,
  c3Keys,
  dictionaryCsvUrl,
  generateDictionary,
  getDictionary,
  listDictionaryVersions,
} from "../../api/c3";
import { ApiError } from "../../api/http";
import { Button, EmptyState, ErrorState, useToasts } from "../../shared";

export default function DictionaryPage() {
  const qc = useQueryClient();
  const toasts = useToasts();
  const [version, setVersion] = useState<string | undefined>(undefined);

  const versions = useQuery({ queryKey: c3Keys.dictionaryVersions(), queryFn: listDictionaryVersions });
  const dict = useQuery({
    queryKey: c3Keys.dictionary(version),
    queryFn: () => getDictionary(version),
    retry: false,
  });

  const generate = useMutation({
    mutationFn: () => {
      const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      return generateDictionary(stamp);
    },
    onSuccess: (r) => {
      toasts.push({ tone: "success", message: `Generated ${r.version} (${r.entities} entities)` });
      setVersion(r.version);
      qc.invalidateQueries({ queryKey: c3Keys.dictionaryVersions() });
      qc.invalidateQueries({ queryKey: ["c3", "dictionary"] });
    },
    onError: (e) => {
      toasts.push({ tone: "error", message: e instanceof ApiError ? e.message : "Could not generate." });
    },
  });

  async function downloadCsv() {
    // The CSV endpoint needs the bearer token; fetch as a blob so the download carries auth.
    const token = getToken();
    const resp = await fetch(dictionaryCsvUrl(version), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) {
      toasts.push({ tone: "error", message: "Could not export the CSV." });
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `data-dictionary-${dict.data?.version ?? "latest"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Data Dictionary</h1>
        <div className="flex items-center gap-2">
          {versions.data && versions.data.length > 0 && (
            <select
              className="rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-xs text-ink"
              value={version ?? ""}
              onChange={(e) => setVersion(e.target.value || undefined)}
              aria-label="Version"
            >
              <option value="">Latest</option>
              {versions.data.map((v) => (
                <option key={v.version} value={v.version}>
                  {v.version}
                </option>
              ))}
            </select>
          )}
          <Button variant="secondary" onClick={downloadCsv} disabled={!dict.data}>
            Export CSV
          </Button>
          <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
            {generate.isPending ? "Generating…" : "Generate"}
          </Button>
        </div>
      </div>

      {dict.isPending ? (
        <div className="py-8 text-center text-sm text-muted">Loading dictionary…</div>
      ) : dict.isError ? (
        dict.error instanceof ApiError && dict.error.status === 404 ? (
          <EmptyState title="No dictionary yet" description="Generate the first version from the live schema." />
        ) : (
          <ErrorState
            message={
              dict.error instanceof ApiError && dict.error.status === 403
                ? "You don't have access to the data dictionary."
                : `Could not load the dictionary: ${dict.error.message}`
            }
            onRetry={() => dict.refetch()}
          />
        )
      ) : (
        <div className="space-y-5">
          <p className="text-xs text-muted">
            Version <span className="font-medium text-ink">{dict.data.version}</span> · generated{" "}
            {new Date(dict.data.generated_at).toLocaleString()}
          </p>
          {dict.data.components.map((c) => (
            <ComponentSection key={c.component} component={c.component} entities={c.entities} />
          ))}
        </div>
      )}
    </div>
  );
}

function ComponentSection({ component, entities }: { component: string; entities: DictEntity[] }) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">{component}</h2>
      <div className="space-y-3">
        {entities.map((e) => (
          <div key={`${e.store}:${e.name}`} className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
            <div className="flex items-center justify-between border-b border-border bg-surface-2 px-4 py-2">
              <span className="font-medium text-ink">{e.name}</span>
              <span className="text-xs text-muted">
                {e.store}
                {e.schema_name ? ` · ${e.schema_name}` : ""}
              </span>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {e.fields.map((f) => (
                  <tr key={f.name} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-1.5 font-mono text-xs text-ink">
                      {f.name}
                      {f.internal && (
                        <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] uppercase text-muted">internal</span>
                      )}
                    </td>
                    <td className="px-4 py-1.5 text-xs text-muted">{f.type}</td>
                    <td className="px-4 py-1.5 text-xs text-muted">{f.description ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </section>
  );
}
