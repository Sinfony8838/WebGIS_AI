import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectPptLibrary } from "../components/ProjectPptLibrary";
import { BrushHistory } from "../lib/brushHistory";
import type { ProjectPresentation } from "../types";

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), prepare: vi.fn(), upload: vi.fn(), image: vi.fn(), session: vi.fn() }));
vi.mock("../api", () => ({ listProjectPresentations: api.list, getProjectPresentation: api.get,
  prepareProjectPresentation: api.prepare, importProjectPresentation: api.upload, buildPublicFileUrl: (url: string) => url }));
vi.mock("../lib/pptSession", () => ({ loadPptSession: api.session, preloadPptImage: api.image, releasePptImages: vi.fn(),
  presentationSessionKey: (scope: string, deck: ProjectPresentation) => `${scope}:${deck.id}` }));

const deck = (id: string): ProjectPresentation => ({ id, title: id, file_name: `${id}.pptx`, status: "ready", renderer: "powerpoint",
  render_version: "1", job_id: "job", error: "", page_count: 2, cover_url: `/${id}.png`,
  slides: [0, 1].map(index => ({ index, image_url: `/${id}-${index}.png`, width: 160, height: 90 })) });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const props = { projectId: "p", userId: "u", currentId: "", viewerOpen: false, onSelect: vi.fn() };

describe("project PPT library", () => {
  beforeEach(() => {
    localStorage.clear(); vi.clearAllMocks();
    api.list.mockResolvedValue({ items: [deck("A"), deck("B")] });
    api.get.mockImplementation(async (_project: string, id: string) => deck(id));
    api.image.mockResolvedValue(undefined);
    api.session.mockResolvedValue({ currentIndex: 0, fullscreen: false, widthPercent: 46, history: new BrushHistory() });
  });
  afterEach(cleanup);

  it("uses one icon to select an imported deck and never calls a desktop connector", async () => {
    render(<ProjectPptLibrary {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    fireEvent.click(await screen.findByRole("button", { name: /A 2 页/ }));
    await waitFor(() => expect(props.onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "A" }), expect.anything(), "u:p:A"));
    expect(api.prepare).not.toHaveBeenCalled(); expect(api.upload).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the previous deck until its replacement image is loaded", async () => {
    const image = deferred<void>(); api.image.mockReturnValue(image.promise);
    render(<ProjectPptLibrary {...props} currentId="B" viewerOpen />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    fireEvent.click(await screen.findByRole("button", { name: /A 2 页/ }));
    await waitFor(() => expect(api.image).toHaveBeenCalled());
    expect(props.onSelect).not.toHaveBeenCalled();
    await act(async () => image.resolve());
    await waitFor(() => expect(props.onSelect).toHaveBeenCalledTimes(1));
  });

  it("ignores an older selection response when a newer deck is chosen", async () => {
    const slow = deferred<ProjectPresentation>();
    api.get.mockImplementation((_p: string, id: string) => id === "A" ? slow.promise : Promise.resolve(deck(id)));
    render(<ProjectPptLibrary {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    fireEvent.click(await screen.findByRole("button", { name: /A 2 页/ }));
    fireEvent.click(screen.getByRole("button", { name: /B 2 页/ }));
    await waitFor(() => expect(props.onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "B" }), expect.anything(), "u:p:B"));
    await act(async () => slow.resolve(deck("A")));
    expect(props.onSelect).toHaveBeenCalledTimes(1);
  });

  it("keeps the active deck on image failure and exposes a useful error", async () => {
    api.image.mockRejectedValue(new Error("页面图像加载失败"));
    render(<ProjectPptLibrary {...props} currentId="B" viewerOpen />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    fireEvent.click(await screen.findByRole("button", { name: /A 2 页/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("页面图像加载失败");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("queries a lost preparation result without posting it twice", async () => {
    const pending = { ...deck("A"), status: "pending" };
    api.get.mockResolvedValueOnce(pending).mockResolvedValue(deck("A"));
    api.prepare.mockRejectedValue(new Error("connection lost"));
    render(<ProjectPptLibrary {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    fireEvent.click(await screen.findByRole("button", { name: /A 2 页/ }));
    await waitFor(() => expect(props.onSelect).toHaveBeenCalledTimes(1));
    expect(api.prepare).toHaveBeenCalledTimes(1); expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("recovers an uploaded request from the list without uploading again", async () => {
    api.upload.mockImplementation(async (_p: string, _file: File, requestId: string) => {
      api.list.mockResolvedValue({ items: [{ ...deck("A"), import_request_id: requestId }] });
      throw new Error("response lost");
    });
    render(<ProjectPptLibrary {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    const input = await screen.findByLabelText("导入项目 PPT");
    fireEvent.change(input, { target: { files: [new File(["source"], "a.pptx")] } });
    await waitFor(() => expect(props.onSelect).toHaveBeenCalledTimes(1));
    expect(api.upload).toHaveBeenCalledTimes(1);
  });

  it("restores the previously open project deck after refresh", async () => {
    localStorage.setItem("ppt-current:u:p", JSON.stringify({ id: "B", open: true }));
    render(<ProjectPptLibrary {...props} />);
    await waitFor(() => expect(props.onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "B" }), expect.anything(), "u:p:B"));
  });

  it("does not commit a selection after its project is unmounted", async () => {
    const image = deferred<void>(); api.image.mockReturnValue(image.promise);
    const view = render(<ProjectPptLibrary {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "PPT 课件" }));
    fireEvent.click(await screen.findByRole("button", { name: /A 2 页/ }));
    await waitFor(() => expect(api.image).toHaveBeenCalled()); view.unmount();
    await act(async () => image.resolve());
    expect(props.onSelect).not.toHaveBeenCalled();
  });
});
