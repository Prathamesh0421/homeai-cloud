/** Current feed config with an edit form (saving creates version n+1) and the versions table. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  INTERVAL_MAX,
  INTERVAL_MIN,
  SENSITIVITIES,
  c1Keys,
  listConfigVersions,
  putFeedConfig,
  restoreConfigVersion,
  type ConfigVersion,
  type Feed,
  type Sensitivity,
} from "../../../api/c1";
import { Button, DataTable, Field, useToasts, type Column } from "../../../shared";
import { Card, inputClass } from "../components";
import { errorText, formatWhen, serverFieldErrors } from "../format";

export interface ConfigCardProps {
  feed: Feed;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  readOnly: boolean;
}

export function ConfigCard({ feed, editing, onEditingChange, readOnly }: ConfigCardProps) {
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const [intervalS, setIntervalS] = useState(String(feed.config.capture_interval_s));
  const [sensitivity, setSensitivity] = useState<Sensitivity>(feed.config.sensitivity);
  const [networkLabel, setNetworkLabel] = useState(feed.config.network_label ?? "");
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: c1Keys.feed(feed.feed_id) });
    void queryClient.invalidateQueries({ queryKey: c1Keys.versions(feed.feed_id) });
    void queryClient.invalidateQueries({ queryKey: ["c1", "feeds"] });
  }

  const save = useMutation({
    mutationFn: () =>
      putFeedConfig(feed.feed_id, {
        capture_interval_s: Number(intervalS),
        sensitivity,
        network_label: networkLabel.trim() || null,
      }),
    onSuccess: (res) => {
      toasts.push({ tone: "success", message: `Config saved as version ${res.config_version}.` });
      onEditingChange(false);
      refresh();
    },
  });

  const server = serverFieldErrors(save.error);
  const errors = { ...server, ...clientErrors };
  const generalError = save.error && Object.keys(server).length === 0 ? errorText(save.error) : null;

  function startEdit() {
    setIntervalS(String(feed.config.capture_interval_s));
    setSensitivity(feed.config.sensitivity);
    setNetworkLabel(feed.config.network_label ?? "");
    setClientErrors({});
    save.reset();
    onEditingChange(true);
  }

  function submit() {
    const n = Number(intervalS);
    const errs: Record<string, string> = {};
    if (!Number.isInteger(n) || n < INTERVAL_MIN || n > INTERVAL_MAX)
      errs.capture_interval_s = `Whole seconds between ${INTERVAL_MIN} and ${INTERVAL_MAX}.`;
    setClientErrors(errs);
    if (!Object.keys(errs).length) save.mutate();
  }

  return (
    <Card
      title={`Configuration · v${feed.config_version}`}
      actions={
        !editing && !readOnly ? (
          <Button variant="secondary" onClick={startEdit}>
            Edit config
          </Button>
        ) : undefined
      }
    >
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="space-y-3"
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={`Capture interval (s, ${INTERVAL_MIN}–${INTERVAL_MAX})`} name="cfg-interval" error={errors.capture_interval_s}>
              <input
                id="cfg-interval"
                type="number"
                className={inputClass}
                value={intervalS}
                onChange={(e) => setIntervalS(e.target.value)}
              />
            </Field>
            <Field label="Sensitivity" name="cfg-sensitivity" error={errors.sensitivity}>
              <select
                id="cfg-sensitivity"
                className={inputClass}
                value={sensitivity}
                onChange={(e) => setSensitivity(e.target.value as Sensitivity)}
              >
                {SENSITIVITIES.map((s) => (
                  <option key={s} value={s}>
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Network label" name="cfg-network" error={errors.network_label}>
              <input
                id="cfg-network"
                className={inputClass}
                value={networkLabel}
                maxLength={60}
                onChange={(e) => setNetworkLabel(e.target.value)}
              />
            </Field>
          </div>
          {generalError && (
            <p role="alert" className="text-sm text-danger">
              {generalError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => onEditingChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Saving…" : `Save as v${feed.config_version + 1}`}
            </Button>
          </div>
        </form>
      ) : (
        <dl className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <dt className="text-xs text-muted">Capture interval</dt>
            <dd className="text-ink">{feed.config.capture_interval_s} s</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Sensitivity</dt>
            <dd className="capitalize text-ink">{feed.config.sensitivity}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Network label</dt>
            <dd className="text-ink">{feed.config.network_label || "—"}</dd>
          </div>
        </dl>
      )}
      {!readOnly && <VersionsTable feed={feed} onRestored={refresh} />}
    </Card>
  );
}

function VersionsTable({ feed, onRestored }: { feed: Feed; onRestored: () => void }) {
  const toasts = useToasts();
  const versions = useQuery({
    queryKey: c1Keys.versions(feed.feed_id),
    queryFn: () => listConfigVersions(feed.feed_id),
  });
  const restore = useMutation({
    mutationFn: (v: number) => restoreConfigVersion(feed.feed_id, v),
    onSuccess: (res, v) => {
      toasts.push({ tone: "success", message: `Restored v${v} as version ${res.config_version}.` });
      onRestored();
    },
    onError: (e) => toasts.push({ tone: "error", message: errorText(e) }),
  });

  const columns: Column<ConfigVersion>[] = [
    {
      key: "version",
      header: "Version",
      render: (v) => (
        <span className="font-medium text-ink">
          v{v.version}
          {v.version === feed.config_version && <span className="ml-1 text-xs font-normal text-success">(current)</span>}
        </span>
      ),
    },
    { key: "interval", header: "Interval", render: (v) => `${v.capture_interval_s} s` },
    { key: "sensitivity", header: "Sensitivity", render: (v) => <span className="capitalize">{v.sensitivity}</span> },
    { key: "network", header: "Network label", render: (v) => v.network_label || "—" },
    { key: "created", header: "Created", render: (v) => formatWhen(v.created_at) },
    {
      key: "restore",
      header: "",
      className: "text-right",
      render: (v) =>
        v.version === feed.config_version ? null : (
          <Button variant="secondary" disabled={restore.isPending} onClick={() => restore.mutate(v.version)}>
            Restore
          </Button>
        ),
    },
  ];

  return (
    <div className="mt-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Config versions</h3>
      {versions.isPending ? (
        <div className="text-sm text-muted">Loading versions…</div>
      ) : versions.isError ? (
        <div className="text-sm text-danger">Could not load versions: {errorText(versions.error)}</div>
      ) : (
        <DataTable columns={columns} rows={versions.data} rowKey={(v) => String(v.version)} empty="No versions yet." />
      )}
    </div>
  );
}
