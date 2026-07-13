import { mkdir, readFile, writeFile, appendFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import type { Message } from "./tool.js";

interface SessionEvent {
  type: "message" | "metadata";
  ts: string;
  data: unknown;
}

interface SessionIndexEntry {
  id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  first_message: string;
  file: string;
}

export class SessionManager {
  private sessionDir: string;
  private currentId: string | null = null;
  private indexPath: string;

  constructor(sessionDir: string) {
    this.sessionDir = sessionDir;
    this.indexPath = join(sessionDir, "index.json");
  }

  async init(): Promise<void> {
    await mkdir(this.sessionDir, { recursive: true });
  }

  /** Create a new session and return its ID */
  async createSession(cwd: string): Promise<string> {
    const id = randomUUID().slice(0, 8);
    this.currentId = id;

    const filePath = this.sessionPath(id);
    const event: SessionEvent = {
      type: "metadata",
      ts: new Date().toISOString(),
      data: { cwd, created: true },
    };
    await writeFile(filePath, JSON.stringify(event) + "\n", "utf-8");

    await this.updateIndex(id, { cwd, firstMessage: "" });
    return id;
  }

  /** Load messages from an existing session */
  async loadSession(id: string): Promise<Message[]> {
    assertValidSessionId(id);
    this.currentId = id;
    const filePath = this.sessionPath(id);
    const raw = await readFile(filePath, "utf-8").catch(() => "");
    if (!raw) return [];

    const messages: Message[] = [];
    for (const line of raw.split("\n")) {
      if (!line.trim()) continue;
      try {
        const event = JSON.parse(line) as SessionEvent;
        if (event.type === "message") {
          messages.push(event.data as Message);
        }
      } catch {
        // skip malformed lines
      }
    }
    return messages;
  }

  /** Append a message to the current session */
  async saveMessage(message: Message): Promise<void> {
    if (!this.currentId) return;
    await this.saveMessageToSession(this.currentId, message);
  }

  /** Append a message to a specific session */
  async saveMessageToSession(id: string, message: Message): Promise<void> {
    assertValidSessionId(id);
    const event: SessionEvent = {
      type: "message",
      ts: new Date().toISOString(),
      data: message,
    };
    await appendFile(this.sessionPath(id), JSON.stringify(event) + "\n", "utf-8");
    await this.updateIndexForMessage(id, message);
  }

  /** List all sessions */
  async listSessions(): Promise<SessionIndexEntry[]> {
    try {
      const raw = await readFile(this.indexPath, "utf-8");
      const entries = JSON.parse(raw) as SessionIndexEntry[];
      return entries.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    } catch {
      return [];
    }
  }

  get currentSessionId(): string | null {
    return this.currentId;
  }

  private sessionPath(id: string): string {
    assertValidSessionId(id);
    return join(this.sessionDir, `${id}.jsonl`);
  }

  private async updateIndex(id: string, meta: { cwd: string; firstMessage: string }): Promise<void> {
    let entries: SessionIndexEntry[] = [];
    try {
      const raw = await readFile(this.indexPath, "utf-8");
      entries = JSON.parse(raw) as SessionIndexEntry[];
    } catch {
      // no index yet
    }

    const now = new Date().toISOString();
    const existing = entries.findIndex((e) => e.id === id);
    const entry: SessionIndexEntry = {
      id,
      created_at: now,
      updated_at: now,
      message_count: 0,
      first_message: meta.firstMessage,
      file: `${id}.jsonl`,
    };

    if (existing >= 0) {
      entries[existing] = { ...entries[existing], updated_at: now };
    } else {
      entries.push(entry);
    }

    await writeFile(this.indexPath, JSON.stringify(entries, null, 2), "utf-8");
  }

  private async updateIndexForMessage(id: string, message: Message): Promise<void> {
    let entries: SessionIndexEntry[] = [];
    try {
      const raw = await readFile(this.indexPath, "utf-8");
      entries = JSON.parse(raw) as SessionIndexEntry[];
    } catch {
      entries = [];
    }

    const now = new Date().toISOString();
    const existing = entries.findIndex((e) => e.id === id);
    if (existing < 0) {
      entries.push({
        id,
        created_at: now,
        updated_at: now,
        message_count: 1,
        first_message: message.role === "user" ? message.content : "",
        file: `${id}.jsonl`,
      });
    } else {
      const entry = entries[existing];
      entries[existing] = {
        ...entry,
        updated_at: now,
        message_count: entry.message_count + 1,
        first_message: entry.first_message || (message.role === "user" ? message.content : ""),
      };
    }

    await writeFile(this.indexPath, JSON.stringify(entries, null, 2), "utf-8");
  }
}

function assertValidSessionId(id: string): void {
  if (!/^[A-Za-z0-9_-]+$/.test(id)) {
    throw new Error(`Invalid session id: ${id}`);
  }
}
