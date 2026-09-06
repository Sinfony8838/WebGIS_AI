/**
 * Noise gate for the always-on microphone ("常开聆听").
 *
 * Classroom audio contains far more than commands: teacher narration,
 * student chatter, background noise that slips past the server VAD. This
 * pure module decides — before anything reaches the backend — whether a
 * final transcript is a deliberate control command:
 *
 *   1. Minimum length (single-word blips are noise).
 *   2. Wake word: the utterance must start with 「小智」(homophone-tolerant,
 *      since ASR may transcribe the name as 小志/小至/小致…). The wake word
 *      is stripped before submission.
 *   3. Command pre-screen: the remaining text must contain a control verb
 *      or keyword, so "小智，今天天气不错" is ignored silently.
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

export type ScreenResult =
  | { accepted: false; reason: "too_short" | "no_wake_word" | "not_a_command" }
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

export function screenTranscript(
  transcript: string,
  options?: { minChars?: number; wakeAliases?: readonly string[]; keywords?: readonly string[] }
): ScreenResult {
  const minChars = options?.minChars ?? 4;
  const text = (transcript || "").trim();
  if (text.replace(/\s/g, "").length < minChars) {
    return { accepted: false, reason: "too_short" };
  }
  const wake = startsWithWakeWord(text);
  if (!wake) {
    return { accepted: false, reason: "no_wake_word" };
  }
  if (!wake.rest) {
    return { accepted: false, reason: "not_a_command" };
  }
  const keywords = options?.keywords ?? COMMAND_KEYWORDS;
  const lowered = wake.rest.toLowerCase();
  const hit = keywords.some((keyword) => lowered.includes(keyword.toLowerCase()));
  if (!hit) {
    return { accepted: false, reason: "not_a_command" };
  }
  return { accepted: true, command: wake.rest.trim(), matchedAlias: wake.alias };
}

/** Human label for the "ignored ambient speech" badge. */
export function describeScreenRejection(reason: "too_short" | "no_wake_word" | "not_a_command"): string {
  switch (reason) {
    case "too_short":
      return "已忽略环境噪音";
    case "no_wake_word":
      return "已忽略环境对话（未唤醒）";
    case "not_a_command":
      return "已忽略非指令发言";
  }
}
