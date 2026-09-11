import { describe, expect, it } from "vitest";
import { describeScreenRejection, screenTranscript } from "../voiceGate";

describe("screenTranscript（direct 模式，智能交互默认）", () => {
  it("无需唤醒词，明确指令直接通过", () => {
    const result = screenTranscript("切换到三维地球");
    expect(result.accepted).toBe(true);
    if (result.accepted) {
      expect(result.command).toBe("切换到三维地球");
    }
  });

  it("兼容「小智 + 指令」并剥离唤醒词", () => {
    const result = screenTranscript("小智，切换到三维地球");
    expect(result.accepted).toBe(true);
    if (result.accepted) {
      expect(result.command).toBe("切换到三维地球");
      expect(result.matchedAlias).toBe("小智");
    }
  });

  it("没有指令关键词的闲聊被忽略", () => {
    const result = screenTranscript("我们今天来讲一讲长江三角洲的气候特征好吗");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("not_a_command");
    }
  });

  it("否定表达不执行（不要切换）", () => {
    const result = screenTranscript("不要切换到三维地球");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("negated");
    }
  });

  it("否定表达不执行（先不打开图层）", () => {
    const result = screenTranscript("先不打开图层管理器");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("negated");
    }
  });

  it("引用他人指令不执行（刚才说切换到三维）", () => {
    const result = screenTranscript("刚才说切换到三维地球的是哪位同学");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("not_directive");
    }
  });

  it("不确定的表述不执行（好像可以切换）", () => {
    const result = screenTranscript("好像可以切换到三维地球的样子");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("not_directive");
    }
  });

  it("过短的噪音片段被忽略", () => {
    const result = screenTranscript("嗯");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("too_short");
    }
  });
});

describe("screenTranscript（wake_word 模式，仅唤醒后执行）", () => {
  const wakeOptions = { mode: "wake_word" as const };

  it("接受「小智 + 指令」并剥离唤醒词", () => {
    const result = screenTranscript("小智，切换到三维地球", wakeOptions);
    expect(result.accepted).toBe(true);
    if (result.accepted) {
      expect(result.command).toBe("切换到三维地球");
      expect(result.matchedAlias).toBe("小智");
    }
  });

  it("容忍唤醒词同音错别字（小志/小至）", () => {
    expect(screenTranscript("小志，打开图层管理", wakeOptions).accepted).toBe(true);
    expect(screenTranscript("小至 进入下一个环节", wakeOptions).accepted).toBe(true);
  });

  it("没有唤醒词的指令被忽略（即使内容像指令）", () => {
    const result = screenTranscript("切换到三维地球", wakeOptions);
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("no_wake_word");
    }
  });

  it("带唤醒词但纯闲聊被忽略（not_a_command）", () => {
    const result = screenTranscript("小智，今天心情不错", wakeOptions);
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("not_a_command");
    }
  });

  it("唤醒词后接指令动词的多种说法都被接受", () => {
    expect(screenTranscript("小智把人口密度图层调到半透明", wakeOptions).accepted).toBe(true);
    expect(screenTranscript("小智，转到长三角", wakeOptions).accepted).toBe(true);
    expect(screenTranscript("小智，开始上课", wakeOptions).accepted).toBe(true);
    expect(screenTranscript("小智，做一个胡焕庸线对比分析", wakeOptions).accepted).toBe(true);
  });

  it("只有唤醒词、没有指令内容被忽略", () => {
    // 「小智」只有两个字，先命中最短长度门（同样是被忽略）。
    const result = screenTranscript("小智", wakeOptions);
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("too_short");
    }
  });
});

describe("describeScreenRejection", () => {
  it("拒绝原因有可读文案", () => {
    expect(describeScreenRejection("no_wake_word")).toContain("未唤醒");
    expect(describeScreenRejection("not_a_command")).toContain("非指令");
    expect(describeScreenRejection("too_short")).toContain("噪音");
    expect(describeScreenRejection("negated")).toContain("否定");
    expect(describeScreenRejection("not_directive")).toContain("不确定");
  });
});
