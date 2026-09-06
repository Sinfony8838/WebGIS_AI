import { describe, expect, it } from "vitest";
import { describeScreenRejection, screenTranscript } from "../voiceGate";

describe("screenTranscript（常开聆听噪音门控）", () => {
  it("接受「小智 + 指令」并剥离唤醒词", () => {
    const result = screenTranscript("小智，切换到三维地球");
    expect(result.accepted).toBe(true);
    if (result.accepted) {
      expect(result.command).toBe("切换到三维地球");
      expect(result.matchedAlias).toBe("小智");
    }
  });

  it("容忍唤醒词同音错别字（小志/小至）", () => {
    expect(screenTranscript("小志，打开图层管理").accepted).toBe(true);
    expect(screenTranscript("小至 进入下一个环节").accepted).toBe(true);
  });

  it("没有唤醒词的环境对话被忽略", () => {
    const result = screenTranscript("我们今天来讲一讲长江三角洲的气候特征");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("no_wake_word");
    }
  });

  it("带唤醒词但纯闲聊被忽略（not_a_command）", () => {
    const result = screenTranscript("小智，今天心情不错");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("not_a_command");
    }
  });

  it("过短的噪音片段被忽略", () => {
    const result = screenTranscript("嗯");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("too_short");
    }
  });

  it("只有唤醒词、没有指令内容被忽略", () => {
    // 「小智」只有两个字，先命中最短长度门（同样是被忽略）。
    const result = screenTranscript("小智");
    expect(result.accepted).toBe(false);
    if (!result.accepted) {
      expect(result.reason).toBe("too_short");
    }
  });

  it("唤醒词后接指令动词的多种说法都被接受", () => {
    expect(screenTranscript("小智把人口密度图层调到半透明").accepted).toBe(true);
    expect(screenTranscript("小智，转到长三角").accepted).toBe(true);
    expect(screenTranscript("小智，开始上课").accepted).toBe(true);
    expect(screenTranscript("小智，做一个胡焕庸线对比分析").accepted).toBe(true);
  });

  it("拒绝原因有可读文案", () => {
    expect(describeScreenRejection("no_wake_word")).toContain("未唤醒");
    expect(describeScreenRejection("not_a_command")).toContain("非指令");
    expect(describeScreenRejection("too_short")).toContain("噪音");
  });
});
