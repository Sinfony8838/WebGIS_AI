/**
 * Noise gate for the always-on microphone (智能交互默认聆听).
 *
 * Classroom audio contains far more than commands: teacher narration,
 * student chatter, background noise that slips past the server VAD. This
 * pure module decides — before anything reaches the backend — whether a
 * final transcript is a deliberate control command.
 *
 * Two modes:
 * - "wake_word": the legacy strict mode (「仅唤醒后执行」setting). The
 *   utterance must start with 「小智」(homophone-tolerant) and the rest
 *   must contain a control keyword. For noisy classrooms.
 * - "direct": the default. Any utterance that carries a clear operation
 *   intent (command keyword) executes without the wake word; wake-word
 *   phrasing still works because the alias is stripped when present.
 *   Negations, quoted/reported commands and hedged speculation are
 *   rejected so ambient speech never reaches the planner.
 *
 * Everything is a pure function of the transcript so it is trivially
 * unit-testable and tunable before a demo.
 */

export const WAKE_WORD_ALIASES = ["小智", "小志", "小至", "小致", "小治", "小知"] as const;

export const COMMAND_KEYWORDS = [
  // view / projection
  "切换", "三维", "3d", "球", "二维", "平面", "2d",
  // panels
  "面板", "图层", "打开", "关闭", "收起",
  // layers
  "显示", "隐藏", "透明", "不透明",
  // focus / fly
  "转到", "飞到", "定位", "回到", "放大", "缩小",
  // lesson flow
  "环节", "下一步", "上一步", "下一", "上一", "进入", "开始上课", "上课", "下课", "结束",
  // analysis
  "分析", "胡焕庸", "密度", "缓冲", "分级",
  // query / explain
  "为什么", "讲解", "解释", "读图", "查询", "搜索",
  // materials
  "素材", "材料", "地图", "底图", "影像",
  // numbers spoken as opacity hints
  "一半", "百分之",
] as const;

/** "不要切换" / "先不打开" — an explicit negative must never execute. */
export const NEGATION_CUES = ["不要", "别把", "别切", "别关", "别打", "别开", "别显", "别隐", "先不", "不用", "无需", "不必", "禁止"] as const;

/** Quoted / reported commands ("刚才说切换到三维") are mentions, not commands. */
export const QUOTE_CUES = ["刚才", "刚刚", "上次", "他说", "她说", "他们说", "比如", "例如", "举个例子"] as const;

/** Hedged speculation ("好像可以切换") is not a deliberate instruction. */
export const HEDGE_CUES = ["好像", "似乎", "可能可以", "也许", "是不是"] as const;

export type GateMode = "direct" | "wake_word";

export type ScreenRejectionReason = "too_short" | "no_wake_word" | "not_a_command" | "negated" | "not_directive";

export type ScreenResult =
  | { accepted: false; reason: ScreenRejectionReason }
  | { accepted: true; command: string; matchedAlias: string };

function stripLeadingPunctuation(text: string): string {
  return text.replace(/^[\s，。、,.!？?：:；;~～]+/, "");
}

function startsWithWakeWord(text: string): { alias: string; rest: string } | null {
  const cleaned = stripLeadingPunctuation(text);
  for (const alias of WAKE_WORD_ALIASES) {
    if (cleaned.startsWith(alias)) {
      let rest = cleaned.slice(alias.length);
      // Common ASR joiners right after the wake word: 「小智，切换…」.
      rest = stripLeadingPunctuation(rest.replace(/^[，,啊嗯的]+/, ""));
      return { alias, rest };
    }
  }
  return null;
}

function containsCommandKeyword(command: string): boolean {
  const lowered = command.toLowerCase();
  return COMMAND_KEYWORDS.some((keyword) => lowered.includes(keyword.toLowerCase()));
}

function containsAny(text: string, cues: readonly string[]): string | null {
  const lowered = text.toLowerCase();
  return cues.find((cue) => lowered.includes(cue.toLowerCase())) || null;
}

export function screenTranscript(
  transcript: string,
  options?: {
    /** "direct" (default) runs without the wake word; "wake_word" requires it. */
    mode?: GateMode;
    minChars?: number;
    wakeAliases?: readonly string[];
    keywords?: readonly string[];
  }
): ScreenResult {
  const minChars = options?.minChars ?? 4;
  const mode: GateMode = options?.mode ?? "direct";
  const text = (transcript || "").trim();
  if (text.replace(/\s/g, "").length < minChars) {
    return { accepted: false, reason: "too_short" };
  }

  const wake = startsWithWakeWord(text);
  const commandText = wake ? wake.rest : mode === "wake_word" ? "" : text;

  if (mode === "wake_word" && !wake) {
    return { accepted: false, reason: "no_wake_word" };
  }
  if (!commandText) {
    return { accepted: false, reason: wake ? "not_a_command" : "too_short" };
  }

  // Direct mode must not fire on negations, quoted commands or hedged
  // speculation — check the full utterance, not just the post-wake rest,
  // so cues spoken before the wake word still count.
  const scanText = wake ? wake.rest : text;
  if (containsAny(scanText, NEGATION_CUES)) {
    return { accepted: false, reason: "negated" };
  }
  if (containsAny(scanText, QUOTE_CUES) || containsAny(scanText, HEDGE_CUES)) {
    return { accepted: false, reason: "not_directive" };
  }

  const keywords = options?.keywords ?? COMMAND_KEYWORDS;
  const lowered = commandText.toLowerCase();
  const hit = keywords.some((keyword) => lowered.includes(keyword.toLowerCase()));
  if (!hit) {
    return { accepted: false, reason: "not_a_command" };
  }
  return { accepted: true, command: commandText.trim(), matchedAlias: wake?.alias ?? "" };
}

/** Human label for the "ignored ambient speech" badge. */
export function describeScreenRejection(reason: ScreenRejectionReason): string {
  switch (reason) {
    case "too_short":
      return "已忽略环境噪音";
    case "no_wake_word":
      return "已忽略环境对话（未唤醒）";
    case "not_a_command":
      return "已忽略非指令发言";
    case "negated":
      return "已忽略否定表达，未执行操作";
    case "not_directive":
      return "已忽略引用或不确定的表述";
  }
}
