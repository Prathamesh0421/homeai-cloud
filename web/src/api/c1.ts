/** C1 IoT Device Manager API client (docs/components/C1_IOT_DEVICE_MANAGER.md §3). */

import { ApiError, clearToken, getToken, http, type Page } from "./http";

// --- enums (contract §3) ------------------------------------------------------------------------

export type MediaKind = "audio" | "video";
export type FeedStatus = "provisioned" | "active" | "inactive" | "error";
export type Connectivity = "online" | "offline" | "unknown";
export type Sensitivity = "low" | "medium" | "high";
export type ClipStatus = "queued" | "processing" | "analyzed" | "failed";
export type RoomType = "bedroom" | "kitchen" | "living" | "bathroom" | "entry" | "other";

export const MEDIA_KINDS: MediaKind[] = ["audio", "video"];
export const FEED_STATUSES: FeedStatus[] = ["provisioned", "active", "inactive", "error"];
export const SENSITIVITIES: Sensitivity[] = ["low", "medium", "high"];
export const CLIP_STATUSES: ClipStatus[] = ["queued", "processing", "analyzed", "failed"];
export const ROOM_TYPES: RoomType[] = ["bedroom", "kitchen", "living", "bathroom", "entry", "other"];

export const INTERVAL_MIN = 5;
export const INTERVAL_MAX = 3600;
export const MAX_CLIP_BYTES = 50 * 1024 * 1024;
/** Content types the ingest endpoint accepts (§3.3). */
export const CLIP_ACCEPT = "audio/wav,audio/x-wav,audio/mpeg,video/mp4,.wav,.mp3,.mp4";

// --- houses and rooms (§3.1) --------------------------------------------------------------------

export interface House {
  house_id: string;
  tenant_id: string;
  name: string;
  address: string | null;
  timezone: string;
  owner_user_id: string | null;
  created_at: string;
  updated_at: string;
  /** Present on GET /houses/{id}; may be missing in the list. */
  room_count?: number;
  feed_count?: number;
}

export interface HouseCreate {
  name: string;
  address?: string;
  timezone: string;
  owner_user_id?: string;
  tenant_id?: string; // required for cloud_staff
}

export type HouseUpdate = Partial<Pick<House, "name" | "address" | "timezone" | "owner_user_id">>;

export interface Room {
  room_id: string;
  house_id: string;
  name: string;
  room_type: RoomType;
  created_at: string;
}

export interface HouseFilters {
  q?: string;
  tenantId?: string;
  page?: number;
  pageSize?: number;
}

export function listHouses(f: HouseFilters = {}): Promise<Page<House>> {
  const q = new URLSearchParams();
  if (f.q) q.set("q", f.q);
  if (f.tenantId) q.set("tenant_id", f.tenantId);
  q.set("page", String(f.page ?? 1));
  q.set("page_size", String(f.pageSize ?? 100));
  return http.getPage<House>(`/api/v1/houses?${q}`);
}

export function getHouse(houseId: string): Promise<House> {
  return http.get<House>(`/api/v1/houses/${encodeURIComponent(houseId)}`);
}

export function createHouse(body: HouseCreate): Promise<House> {
  return http.post<House>("/api/v1/houses", body);
}

export function updateHouse(houseId: string, body: HouseUpdate): Promise<House> {
  return http.patch<House>(`/api/v1/houses/${encodeURIComponent(houseId)}`, body);
}

export function deleteHouse(houseId: string): Promise<void> {
  return http.delete<void>(`/api/v1/houses/${encodeURIComponent(houseId)}`);
}

/** Not paged (≤ 50 rooms); ``http`` unwraps ``data`` whether or not ``meta`` is present. */
export function listRooms(houseId: string): Promise<Room[]> {
  return http.get<Room[]>(`/api/v1/houses/${encodeURIComponent(houseId)}/rooms`);
}

export function createRoom(houseId: string, body: { name: string; room_type: RoomType }): Promise<Room> {
  return http.post<Room>(`/api/v1/houses/${encodeURIComponent(houseId)}/rooms`, body);
}

export function updateRoom(roomId: string, body: { name?: string; room_type?: RoomType }): Promise<Room> {
  return http.patch<Room>(`/api/v1/rooms/${encodeURIComponent(roomId)}`, body);
}

export function deleteRoom(roomId: string): Promise<void> {
  return http.delete<void>(`/api/v1/rooms/${encodeURIComponent(roomId)}`);
}

// --- feeds (§3.2) -------------------------------------------------------------------------------

export interface FeedConfig {
  capture_interval_s: number;
  sensitivity: Sensitivity;
  network_label?: string | null;
}

export interface Feed {
  feed_id: string;
  tenant_id: string;
  house_id: string;
  house_name: string | null;
  room_id: string | null;
  room_name: string | null;
  name: string;
  media_kind: MediaKind;
  status: FeedStatus;
  is_enabled: boolean;
  connectivity_status: Connectivity;
  config: FeedConfig;
  config_version: number;
  last_clip_at: string | null;
  created_at: string;
  archived_at: string | null;
}

export interface FeedDetail extends Feed {
  recent_clips: ClipSummary[];
}

export interface FeedCreate {
  name: string;
  media_kind: MediaKind;
  house_id: string;
  room_id?: string;
  config: FeedConfig;
}

export interface ConfigVersion {
  version: number;
  capture_interval_s: number;
  sensitivity: Sensitivity;
  network_label: string | null;
  created_by: string;
  created_at: string;
}

export interface ConfigResult {
  config_version: number;
  config: FeedConfig;
}

export interface FeedStats {
  houses: number;
  total: number;
  by_status: Partial<Record<FeedStatus, number>>;
  online: number;
}

export interface FeedFilters {
  houseId?: string;
  roomId?: string;
  mediaKind?: MediaKind;
  status?: FeedStatus;
  connectivity?: Connectivity;
  isEnabled?: boolean;
  includeArchived?: boolean;
  page?: number;
  pageSize?: number;
}

export function feedsQuery(f: FeedFilters): string {
  const q = new URLSearchParams();
  if (f.houseId) q.set("house_id", f.houseId);
  if (f.roomId) q.set("room_id", f.roomId);
  if (f.mediaKind) q.set("media_kind", f.mediaKind);
  if (f.status) q.set("status", f.status);
  if (f.connectivity) q.set("connectivity_status", f.connectivity);
  if (f.isEnabled !== undefined) q.set("is_enabled", String(f.isEnabled));
  if (f.includeArchived) q.set("include_archived", "true");
  q.set("page", String(f.page ?? 1));
  q.set("page_size", String(f.pageSize ?? 25));
  return q.toString();
}

export function listFeeds(f: FeedFilters = {}): Promise<Page<Feed>> {
  return http.getPage<Feed>(`/api/v1/feeds?${feedsQuery(f)}`);
}

export function getFeed(feedId: string): Promise<FeedDetail> {
  return http.get<FeedDetail>(`/api/v1/feeds/${encodeURIComponent(feedId)}`);
}

export function createFeed(body: FeedCreate): Promise<Feed> {
  return http.post<Feed>("/api/v1/feeds", body);
}

/** ``room_id: null`` unassigns the room (409 ``room_required`` on an enabled feed). */
export function updateFeed(feedId: string, body: { name?: string; room_id?: string | null }): Promise<Feed> {
  return http.patch<Feed>(`/api/v1/feeds/${encodeURIComponent(feedId)}`, body);
}

/** Enable needs a room: 409 ``room_required``. */
export function setFeedEnabled(feedId: string, isEnabled: boolean): Promise<Feed> {
  return http.patch<Feed>(`/api/v1/feeds/${encodeURIComponent(feedId)}/status`, { is_enabled: isEnabled });
}

/** Archive (soft delete). */
export function archiveFeed(feedId: string): Promise<void> {
  return http.delete<void>(`/api/v1/feeds/${encodeURIComponent(feedId)}`);
}

export function putFeedConfig(feedId: string, config: FeedConfig): Promise<ConfigResult> {
  return http.put<ConfigResult>(`/api/v1/feeds/${encodeURIComponent(feedId)}/config`, config);
}

/** Newest first. */
export function listConfigVersions(feedId: string): Promise<ConfigVersion[]> {
  return http.get<ConfigVersion[]>(`/api/v1/feeds/${encodeURIComponent(feedId)}/config-versions`);
}

/** Copies version ``v`` into a new version n+1. */
export function restoreConfigVersion(feedId: string, version: number): Promise<ConfigResult> {
  return http.post<ConfigResult>(
    `/api/v1/feeds/${encodeURIComponent(feedId)}/config-versions/${version}/restore`,
  );
}

export function getFeedStats(params: { tenantId?: string; houseId?: string } = {}): Promise<FeedStats> {
  const q = new URLSearchParams();
  if (params.tenantId) q.set("tenant_id", params.tenantId);
  if (params.houseId) q.set("house_id", params.houseId);
  const qs = q.toString();
  return http.get<FeedStats>(`/api/v1/feeds/stats${qs ? `?${qs}` : ""}`);
}

// --- ingest and clips (§3.3) --------------------------------------------------------------------

export interface ClipSummary {
  media_id: string;
  house_id?: string;
  /** Tells same-named feeds of different houses apart (every seeded house has a "Kitchen Mic"). */
  house_name?: string | null;
  feed_id: string;
  feed_name: string | null;
  room_name: string | null;
  media_kind: MediaKind;
  captured_at: string;
  uploaded_at: string;
  size: number;
  status: ClipStatus;
  detection_id: string | null;
  /** Only guaranteed on GET /clips/{id}; shown in lists when the server includes it. */
  top_label?: string | null;
}

export interface ClipDetail extends ClipSummary {
  tenant_id?: string;
  house_id?: string;
  room_id?: string | null;
  client_clip_id?: string | null;
  top_label?: string | null;
  error?: string | null;
}

export interface ClipFilters {
  houseId?: string;
  feedId?: string;
  roomId?: string;
  status?: ClipStatus;
  from?: string; // ISO-8601 UTC
  to?: string;
  page?: number;
  pageSize?: number;
}

export interface PlaybackUrl {
  url: string;
  expires_at: string;
}

export interface IngestResult {
  media_id: string;
  status: ClipStatus;
  s3_key: string;
  duplicate: boolean;
}

export interface ClipUpload {
  feedId: string;
  mediaKind: MediaKind;
  capturedAt: string; // ISO-8601 UTC
  clientClipId?: string;
  file: File | Blob;
}

export function clipsQuery(f: ClipFilters): string {
  const q = new URLSearchParams();
  if (f.houseId) q.set("house_id", f.houseId);
  if (f.feedId) q.set("feed_id", f.feedId);
  if (f.roomId) q.set("room_id", f.roomId);
  if (f.status) q.set("status", f.status);
  if (f.from) q.set("from", f.from);
  if (f.to) q.set("to", f.to);
  q.set("page", String(f.page ?? 1));
  q.set("page_size", String(f.pageSize ?? 25));
  return q.toString();
}

export function listClips(f: ClipFilters = {}): Promise<Page<ClipSummary>> {
  return http.getPage<ClipSummary>(`/api/v1/clips?${clipsQuery(f)}`);
}

export function getClip(mediaId: string): Promise<ClipDetail> {
  return http.get<ClipDetail>(`/api/v1/clips/${encodeURIComponent(mediaId)}`);
}

/** A fresh 15-minute presigned URL; call it right before playing. */
export function getPlaybackUrl(mediaId: string): Promise<PlaybackUrl> {
  return http.get<PlaybackUrl>(`/api/v1/clips/${encodeURIComponent(mediaId)}/playback-url`);
}

/**
 * ``POST /ingest/clip`` as multipart. Uses ``fetch`` directly because ``http`` always sends JSON;
 * errors map to ``ApiError`` the same way (a 401 clears the token). 201 = new clip, 200 =
 * ``duplicate: true`` (same ``client_clip_id`` already stored for this feed).
 */
export async function uploadClip(u: ClipUpload): Promise<IngestResult> {
  const form = new FormData();
  form.set("feed_id", u.feedId);
  form.set("media_kind", u.mediaKind);
  form.set("captured_at", u.capturedAt);
  if (u.clientClipId) form.set("client_clip_id", u.clientClipId);
  form.set("file", u.file);

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch("/api/v1/ingest/clip", { method: "POST", headers, body: form });
  const text = await resp.text();
  let parsed: { data?: IngestResult; error?: { code?: string; message?: string; details?: unknown } } | undefined;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    parsed = undefined; // e.g. Caddy's plain-text 413
  }
  if (!resp.ok) {
    if (resp.status === 401) clearToken();
    const err = parsed?.error ?? {};
    const fallback = resp.status === 413 ? "File is larger than 50 MB." : resp.statusText || "error";
    throw new ApiError(
      resp.status,
      err.code ?? (resp.status === 413 ? "payload_too_large" : "unknown"),
      err.message ?? fallback,
      err.details,
    );
  }
  return (parsed?.data ?? parsed) as IngestResult;
}

// --- query keys ---------------------------------------------------------------------------------

export const c1Keys = {
  all: ["c1"] as const,
  houses: (f: HouseFilters = {}) => ["c1", "houses", f] as const,
  house: (houseId: string) => ["c1", "house", houseId] as const,
  rooms: (houseId: string) => ["c1", "rooms", houseId] as const,
  feeds: (f: FeedFilters = {}) => ["c1", "feeds", f] as const,
  feed: (feedId: string) => ["c1", "feed", feedId] as const,
  versions: (feedId: string) => ["c1", "versions", feedId] as const,
  clips: (f: ClipFilters = {}) => ["c1", "clips", f] as const,
  clip: (mediaId: string) => ["c1", "clip", mediaId] as const,
  stats: () => ["c1", "stats"] as const,
};
