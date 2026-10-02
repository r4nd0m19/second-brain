/** 扩展内消息协议（content ↔ SW ↔ offscreen）。 */

export interface PageReadMessage {
  target: "sw";
  type: "page-read";
  url: string;
  title: string;
  text: string;
  capturedAt: string;
  captureId: string;
}

export interface SnapshotChunkMessage {
  target: "sw";
  type: "snapshot-chunk";
  captureId: string;
  index: number;
  total: number;
  /** base64（消息为 JSON 序列化，二进制须编码；单块 ≤3MB） */
  data: string;
}

export interface SnapshotFailedMessage {
  target: "sw";
  type: "snapshot-failed";
  captureId: string;
  reason: string;
}

export interface SnapshotCompleteMessage {
  target: "sw";
  type: "snapshot-complete";
  captureId: string;
  total: number;
}

/** 采集完成反馈（SW → 页面内容脚本：右下角提示） */
export interface CaptureDoneMessage {
  target: "content";
  type: "capture-done";
  withSnapshot: boolean;
}

export interface SpaNavMessage {
  target: "content";
  type: "spa-nav";
}

export interface UploadJob {
  captureId: string;
  url: string;
  title: string;
  text: string;
  capturedAt: string;
  hasSnapshot: boolean;
  serverUrl: string;
  token: string;
}

export interface UploadRequestMessage {
  target: "offscreen";
  type: "upload";
  job: UploadJob;
}

export interface UploadResultMessage {
  target: "sw";
  type: "upload-result";
  captureId: string;
  ok: boolean;
  status?: number;
  error?: string;
  retryAfterSeconds?: number;
  /** 永久失败（400/404 等）：不再重试 */
  permanent?: boolean;
  /** 本次上传是否附带了快照（用于完成提示文案） */
  withSnapshot?: boolean;
}

/** 待传/重试队列条目（storage.local） */
export interface QueueEntry {
  captureId: string;
  url: string;
  title: string;
  text: string;
  capturedAt: string;
  attempts: number;
  nextRetryAt: number;
  status: "pending" | "auth-error" | "dead";
  /** 服务器 413 后降级为仅正文重试 */
  snapshotDropped: boolean;
  /** 入队时间（ms；快照等待超时判定用） */
  queuedAt: number;
  /** 来源标签页（完成提示/徽标用；无则 null） */
  tabId: number | null;
  /** 快照分片仍在传输中（true 时上传等待，最长 30s） */
  snapshotPending: boolean;
  /** 内容脚本声明的分片总数（完整性校验用） */
  snapshotTotal: number | null;
}
