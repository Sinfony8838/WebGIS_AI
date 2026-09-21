import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ChinaInquiryGuide, type ChinaInquiryContent } from "../components/ChinaInquiryGuide";
import type { ClassSessionRecord } from "../types";
const step = (title: string) => ({ title, task: `${title}任务`, hint: "只比较颜色", teacher: "教师解释" });
const content: ChinaInquiryContent = { china_inquiry:[step("观察"),step("绘线"),step("依据")], china_explain:[step("比较"),step("例外"),step("归纳")], conclusion:"归纳参考答案" };
const session = { session_id:"s", events:[] } as unknown as ClassSessionRecord;
afterEach(cleanup);

it("reveals one task at a time and leaves reference-line reveal to the teacher",async()=>{
  const onSave=vi.fn().mockResolvedValue(undefined), onEnterStage=vi.fn();
  render(<ChinaInquiryGuide {...{content,session,onSave,onEnterStage}} stageId="china_inquiry" busy={false}/>);
  expect(screen.queryByText("教师解释")).toBeNull();
  expect(screen.queryByText("归纳参考答案")).toBeNull();
  expect(screen.queryByText("绘线任务")).toBeNull();
  fireEvent.click(screen.getByText("给一条提示"));
  expect(screen.getByText("只比较颜色")).toBeVisible();
  fireEvent.click(screen.getByText("下一步"));
  await waitFor(()=>expect(screen.getByText("绘线任务")).toBeVisible());
  fireEvent.click(screen.getByText("下一步"));
  await waitFor(()=>expect(screen.getByText("依据任务")).toBeVisible());
  expect(onEnterStage).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("揭示参考线并比较"));
  expect(onEnterStage).toHaveBeenCalledWith("china_explain");
  expect(onSave.mock.calls.every(([p])=>p.kind==="inquiry_navigation")).toBe(true);
});

it("restores the step from real session events and retains failed drafts",async()=>{
  const saved = {...session,events:[{event_id:"e",type:"note",stage_id:"china_explain",timestamp:"",payload:{kind:"inquiry_navigation",step:2}}]};
  const onSave=vi.fn().mockRejectedValue(new Error("网络暂不可用"));
  render(<ChinaInquiryGuide content={content} session={saved} stageId="china_explain" busy={false} onSave={onSave} onEnterStage={vi.fn()}/>);
  expect(screen.getByText("归纳任务")).toBeVisible();
  expect(screen.getByText("观点与归纳 · 未采集")).toBeVisible();
  fireEvent.click(screen.getByText("教师参考"));
  fireEvent.click(screen.getByText("确认并保留归纳"));
  await waitFor(()=>expect(screen.getByRole("alert")).toHaveTextContent("网络暂不可用"));
  expect(screen.getByLabelText("教师归纳草稿")).toHaveValue("归纳参考答案");
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({source:"teacher_confirmed",record_kind:"conclusion"}));
});
