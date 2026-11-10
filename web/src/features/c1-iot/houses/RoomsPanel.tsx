/** Rooms of one house: add, rename / retype, delete (409 room_in_use shown inline). */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ROOM_TYPES,
  c1Keys,
  createRoom,
  deleteRoom,
  listRooms,
  updateRoom,
  type House,
  type Room,
  type RoomType,
} from "../../../api/c1";
import { Button, ConfirmDialog, useToasts } from "../../../shared";
import { Card, inputClass, selectClass } from "../components";
import { errorText, labelText, serverFieldErrors } from "../format";

export function RoomsPanel({ house }: { house: House }) {
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const rooms = useQuery({ queryKey: c1Keys.rooms(house.house_id), queryFn: () => listRooms(house.house_id) });
  const [name, setName] = useState("");
  const [roomType, setRoomType] = useState<RoomType>("living");
  const [editing, setEditing] = useState<Room | null>(null);
  const [deleting, setDeleting] = useState<Room | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: c1Keys.rooms(house.house_id) });
    void queryClient.invalidateQueries({ queryKey: ["c1", "houses"] });
  }

  const add = useMutation({
    mutationFn: () => createRoom(house.house_id, { name: name.trim(), room_type: roomType }),
    onSuccess: (r) => {
      toasts.push({ tone: "success", message: `Room “${r.name}” added.` });
      setName("");
      refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (room: Room) => deleteRoom(room.room_id),
    onSuccess: (_v, room) => {
      toasts.push({ tone: "success", message: `Room “${room.name}” deleted.` });
      setInlineError(null);
      refresh();
    },
    onError: (e) => {
      setInlineError(errorText(e));
      toasts.push({ tone: "error", message: errorText(e), ttl: 7000 });
      refresh();
    },
  });

  const addErrors = serverFieldErrors(add.error);
  const addGeneral = add.error && Object.keys(addErrors).length === 0 ? errorText(add.error) : null;

  return (
    <Card title={`Rooms in ${house.name}`}>
      {rooms.isPending ? (
        <div className="text-sm text-muted">Loading rooms…</div>
      ) : rooms.isError ? (
        <div className="text-sm text-danger">Could not load rooms: {errorText(rooms.error)}</div>
      ) : rooms.data.length === 0 ? (
        <p className="text-sm text-muted">No rooms yet — add the first one below.</p>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {rooms.data.map((room) =>
            editing?.room_id === room.room_id ? (
              <RoomEditRow
                key={room.room_id}
                room={room}
                onDone={() => {
                  setEditing(null);
                  refresh();
                }}
              />
            ) : (
              <li key={room.room_id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span>
                  <span className="font-medium text-ink">{room.name}</span>
                  <span className="ml-2 text-xs text-muted">{labelText(room.room_type)}</span>
                </span>
                <span className="flex gap-2">
                  <Button variant="ghost" onClick={() => setEditing(room)}>
                    Rename
                  </Button>
                  <Button variant="ghost" onClick={() => setDeleting(room)}>
                    Delete
                  </Button>
                </span>
              </li>
            ),
          )}
        </ul>
      )}

      {inlineError && (
        <p role="alert" className="mt-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          {inlineError}
        </p>
      )}

      <form
        className="mt-3 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) add.mutate();
        }}
      >
        <div>
          <label htmlFor={`room-name-${house.house_id}`} className="block text-xs text-muted">
            New room name
          </label>
          <input
            id={`room-name-${house.house_id}`}
            className={inputClass}
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor={`room-type-${house.house_id}`} className="block text-xs text-muted">
            Type
          </label>
          <select
            id={`room-type-${house.house_id}`}
            className={selectClass}
            value={roomType}
            onChange={(e) => setRoomType(e.target.value as RoomType)}
          >
            {ROOM_TYPES.map((t) => (
              <option key={t} value={t}>
                {labelText(t)}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={!name.trim() || add.isPending}>
          {add.isPending ? "Adding…" : "+ Add room"}
        </Button>
      </form>
      {(addErrors.name || addErrors.room_type || addGeneral) && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {addErrors.name ?? addErrors.room_type ?? addGeneral}
        </p>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete room?"
        message={deleting ? `Delete “${deleting.name}”? A room that a feed still uses cannot be deleted.` : ""}
        confirmLabel="Delete"
        destructive
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
          setDeleting(null);
        }}
      />
    </Card>
  );
}

function RoomEditRow({ room, onDone }: { room: Room; onDone: () => void }) {
  const toasts = useToasts();
  const [name, setName] = useState(room.name);
  const [roomType, setRoomType] = useState<RoomType>(room.room_type);
  const save = useMutation({
    mutationFn: () => updateRoom(room.room_id, { name: name.trim(), room_type: roomType }),
    onSuccess: () => {
      toasts.push({ tone: "success", message: "Room updated." });
      onDone();
    },
  });
  const errs = serverFieldErrors(save.error);
  return (
    <li className="px-3 py-2">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) save.mutate();
        }}
      >
        <input
          aria-label="Room name"
          className={`${inputClass} w-48`}
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          aria-label="Room type"
          className={selectClass}
          value={roomType}
          onChange={(e) => setRoomType(e.target.value as RoomType)}
        >
          {ROOM_TYPES.map((t) => (
            <option key={t} value={t}>
              {labelText(t)}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={save.isPending}>
          Save
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </form>
      {save.isError && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {errs.name ?? errs.room_type ?? errorText(save.error)}
        </p>
      )}
    </li>
  );
}
