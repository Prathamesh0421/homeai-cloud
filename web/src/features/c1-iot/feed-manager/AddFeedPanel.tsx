/** "+ Add feed" form (Camera Feed Manager). New feeds start provisioned and disabled. */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  INTERVAL_MAX,
  INTERVAL_MIN,
  MEDIA_KINDS,
  SENSITIVITIES,
  c1Keys,
  createFeed,
  listRooms,
  type Feed,
  type House,
  type MediaKind,
  type Sensitivity,
} from "../../../api/c1";
import { Button, Field, FormPanel } from "../../../shared";
import { inputClass } from "../components";
import { errorText, serverFieldErrors } from "../format";

export interface AddFeedPanelProps {
  houses: House[];
  defaultHouseId?: string;
  onCreated: (feed: Feed) => void;
  onCancel: () => void;
}

export function AddFeedPanel({ houses, defaultHouseId, onCreated, onCancel }: AddFeedPanelProps) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<MediaKind>("audio");
  const [houseId, setHouseId] = useState(defaultHouseId ?? houses[0]?.house_id ?? "");
  const [roomId, setRoomId] = useState("");
  const [intervalS, setIntervalS] = useState("30");
  const [sensitivity, setSensitivity] = useState<Sensitivity>("medium");
  const [networkLabel, setNetworkLabel] = useState("");
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const rooms = useQuery({
    queryKey: c1Keys.rooms(houseId),
    queryFn: () => listRooms(houseId),
    enabled: !!houseId,
  });

  const create = useMutation({ mutationFn: createFeed, onSuccess: onCreated });
  const server = serverFieldErrors(create.error);
  const errors = { ...server, ...clientErrors };
  const generalError = create.error && Object.keys(server).length === 0 ? errorText(create.error) : null;

  function submit() {
    const errs: Record<string, string> = {};
    const n = Number(intervalS);
    if (!name.trim()) errs.name = "Name is required.";
    if (!houseId) errs.house_id = "Choose a house.";
    if (!Number.isInteger(n) || n < INTERVAL_MIN || n > INTERVAL_MAX)
      errs.capture_interval_s = `Whole seconds between ${INTERVAL_MIN} and ${INTERVAL_MAX}.`;
    setClientErrors(errs);
    if (Object.keys(errs).length) return;
    create.mutate({
      name: name.trim(),
      media_kind: kind,
      house_id: houseId,
      ...(roomId ? { room_id: roomId } : {}),
      config: {
        capture_interval_s: n,
        sensitivity,
        ...(networkLabel.trim() ? { network_label: networkLabel.trim() } : {}),
      },
    });
  }

  return (
    <FormPanel
      title="Add feed"
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Adding…" : "Add feed"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" name="feed-name" error={errors.name}>
          <input id="feed-name" className={inputClass} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Kind" name="feed-kind" error={errors.media_kind}>
          <select id="feed-kind" className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as MediaKind)}>
            {MEDIA_KINDS.map((k) => (
              <option key={k} value={k}>
                {k === "audio" ? "Audio" : "Video"}
              </option>
            ))}
          </select>
        </Field>
        <Field label="House" name="feed-house" error={errors.house_id}>
          <select
            id="feed-house"
            className={inputClass}
            value={houseId}
            onChange={(e) => {
              setHouseId(e.target.value);
              setRoomId("");
            }}
          >
            {houses.length === 0 && <option value="">No houses — add one first</option>}
            {houses.map((h) => (
              <option key={h.house_id} value={h.house_id}>
                {h.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Room (optional)" name="feed-room" error={errors.room_id}>
          <select id="feed-room" className={inputClass} value={roomId} onChange={(e) => setRoomId(e.target.value)}>
            <option value="">No room yet</option>
            {rooms.data?.map((r) => (
              <option key={r.room_id} value={r.room_id}>
                {r.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={`Capture interval (s, ${INTERVAL_MIN}–${INTERVAL_MAX})`} name="feed-interval" error={errors.capture_interval_s}>
          <input
            id="feed-interval"
            type="number"
            className={inputClass}
            value={intervalS}
            onChange={(e) => setIntervalS(e.target.value)}
          />
        </Field>
        <Field label="Sensitivity" name="feed-sensitivity" error={errors.sensitivity}>
          <select
            id="feed-sensitivity"
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
        <Field label="Network label (optional)" name="feed-network" error={errors.network_label}>
          <input
            id="feed-network"
            className={inputClass}
            value={networkLabel}
            maxLength={60}
            placeholder="e.g. HomeWiFi-2G"
            onChange={(e) => setNetworkLabel(e.target.value)}
          />
        </Field>
      </div>
      <p className="text-xs text-muted">
        Connectivity is recorded from clip uploads, not measured. A new feed starts provisioned and disabled; assign a
        room before enabling it.
      </p>
      {generalError && (
        <p role="alert" className="text-sm text-danger">
          {generalError}
        </p>
      )}
    </FormPanel>
  );
}
