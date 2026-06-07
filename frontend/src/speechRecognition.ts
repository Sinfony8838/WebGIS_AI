export type SpeechRecognitionAlternativeLike = {
  transcript: string;
};

export type SpeechRecognitionResultLike = {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
};

export type SpeechRecognitionEventLike = {
  resultIndex?: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
};

export type SpeechRecognitionErrorEventLike = {
  error: string;
  message?: string;
};

export interface BrowserSpeechRecognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

export type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

type WindowWithSpeechRecognition = Window &
  typeof globalThis & {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  };

export function getSpeechRecognitionConstructor(
  targetWindow: Window & typeof globalThis = window
): BrowserSpeechRecognitionConstructor | null {
  const speechWindow = targetWindow as WindowWithSpeechRecognition;
  return speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition || null;
}

export function getSpeechRecognitionErrorMessage(errorCode: string): { title: string; detail: string } {
  switch (errorCode) {
    case "not-allowed":
    case "service-not-allowed":
      return {
        title: "语音权限不可用",
        detail: "浏览器没有授予麦克风权限，请允许访问麦克风后重试。"
      };
    case "audio-capture":
      return {
        title: "未检测到麦克风",
        detail: "当前设备没有可用的音频输入设备。"
      };
    case "no-speech":
      return {
        title: "没有识别到语音",
        detail: "请靠近麦克风并在点击后直接说出课堂指令。"
      };
    case "network":
      return {
        title: "语音识别失败",
        detail: "浏览器语音识别服务暂时不可用，请稍后重试。"
      };
    default:
      return {
        title: "语音识别失败",
        detail: "浏览器没有返回可用的识别结果，请重试一次。"
      };
  }
}
