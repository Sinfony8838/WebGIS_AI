import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { UploadDialog } from "../components/UploadDialog";

function makeFile(name: string, contents: string) {
  return new File([contents], name, { type: "text/plain" });
}

function pickFile(name: string, contents = "name,lon,lat\nA,113.2,23.1\n") {
  const input = screen.getByLabelText(/选择文件/) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [makeFile(name, contents)] } });
}

afterEach(() => cleanup());

describe("UploadDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <UploadDialog open={false} busy={false} onClose={() => {}} onSubmit={() => {}} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("survives being mounted closed and then opened (hooks order regression)", () => {
    // Regression: useCallback must run before the `if (!open) return null`
    // early return, otherwise opening the dialog after mount crashes React
    // with "Rendered more hooks than during the previous render".
    const { rerender } = render(
      <UploadDialog open={false} busy={false} onClose={() => {}} onSubmit={() => {}} />
    );
    rerender(<UploadDialog open busy={false} onClose={() => {}} onSubmit={() => {}} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    rerender(<UploadDialog open={false} busy={false} onClose={() => {}} onSubmit={() => {}} />);
    rerender(<UploadDialog open busy={false} onClose={() => {}} onSubmit={() => {}} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows CSV field inputs only for csv files and defaults to auto-detect", () => {
    render(<UploadDialog open busy={false} onClose={() => {}} onSubmit={() => {}} />);
    pickFile("points.csv");
    expect(screen.getByLabelText(/纬度字段/)).toHaveValue("");
    expect(screen.getByPlaceholderText(/留空自动识别（lat \/ 纬度）/)).toBeInTheDocument();
  });

  it("hides csv field inputs for geojson files", () => {
    render(<UploadDialog open busy={false} onClose={() => {}} onSubmit={() => {}} />);
    pickFile("points.geojson");
    expect(screen.queryByLabelText(/纬度字段/)).not.toBeInTheDocument();
  });

  it("shows bounds inputs for image files", () => {
    render(<UploadDialog open busy={false} onClose={() => {}} onSubmit={() => {}} />);
    pickFile("overlay.png");
    expect(screen.getByLabelText(/西界（经度）/)).toBeInTheDocument();
    expect(screen.getByLabelText(/北界（纬度）/)).toBeInTheDocument();
  });

  it("sends only the file (no empty lat/lon fields) on submit", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<UploadDialog open busy={false} onClose={onClose} onSubmit={onSubmit} />);
    pickFile("points.csv");
    fireEvent.click(screen.getByRole("button", { name: "导入到课堂" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const formData = onSubmit.mock.calls[0][0] as FormData;
    expect(formData.get("file")).toBeInstanceOf(File);
    expect(formData.get("lat_field")).toBeNull();
    expect(formData.get("lon_field")).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("forwards explicit field names and dataset name", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<UploadDialog open busy={false} onClose={() => {}} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText(/数据名称/), {
      target: { value: "课堂调查点位" }
    });
    pickFile("points.csv");
    fireEvent.change(screen.getByLabelText(/纬度字段/), { target: { value: "纬度" } });
    fireEvent.change(screen.getByLabelText(/经度字段/), { target: { value: "经度" } });
    fireEvent.click(screen.getByRole("button", { name: "导入到课堂" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const formData = onSubmit.mock.calls[0][0] as FormData;
    expect(formData.get("dataset_name")).toBe("课堂调查点位");
    expect(formData.get("lat_field")).toBe("纬度");
    expect(formData.get("lon_field")).toBe("经度");
  });

  it("shows an inline Chinese error and stays open when submit rejects", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(new Error("CSV 中没有可导入的坐标行：全部 1 行都被跳过。"));
    const onClose = vi.fn();
    render(<UploadDialog open busy={false} onClose={onClose} onSubmit={onSubmit} />);
    pickFile("points.csv");
    fireEvent.click(screen.getByRole("button", { name: "导入到课堂" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("导入失败");
    expect(alert).toHaveTextContent("没有可导入的坐标行");
    expect(onClose).not.toHaveBeenCalled();
    // The submit button recovers so the user can retry after fixing the file.
    expect(screen.getByRole("button", { name: "导入到课堂" })).toBeEnabled();
  });

  it("disables the submit button while uploading", async () => {
    let resolveSubmit: (value: unknown) => void = () => {};
    const onSubmit = vi.fn().mockImplementation(() => new Promise((resolve) => { resolveSubmit = resolve; }));
    render(<UploadDialog open busy={false} onClose={() => {}} onSubmit={onSubmit} />);
    pickFile("points.csv");
    fireEvent.click(screen.getByRole("button", { name: "导入到课堂" }));
    expect(screen.getByRole("button", { name: "正在导入…" })).toBeDisabled();
    resolveSubmit(undefined);
    await waitFor(() => expect(screen.queryByRole("button", { name: "正在导入…" })).not.toBeInTheDocument());
  });

  it("renders the natural-Chinese import report when the backend returns a summary", async () => {
    const summary = {
      message: "成功导入 980 条记录，20 条被跳过（7 条坐标缺失、7 条坐标不是有效数字、6 条坐标超出经纬度范围）。",
      layer: {
        name: "课堂调查点位",
        metadata: { feature_count: 980, source_crs: "EPSG:4326", stored_crs: "EPSG:4326", crs_converted: false }
      },
      crs: { source_crs: "EPSG:4326", target_crs: "EPSG:4326", reprojected: false, warnings: [] },
      row_report: {
        total_rows: 1000,
        imported_rows: 980,
        skipped_rows: 20,
        skip_reasons: { 坐标缺失: 7, 坐标不是有效数字: 7, 坐标超出经纬度范围: 6 }
      }
    };
    const onSubmit = vi.fn().mockResolvedValue(summary);
    const onClose = vi.fn();
    render(<UploadDialog open busy={false} onClose={onClose} onSubmit={onSubmit} />);
    pickFile("points.csv");
    fireEvent.click(screen.getByRole("button", { name: "导入到课堂" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("成功导入 980 条记录");
    expect(status).toHaveTextContent("共 1000 行，成功 980 行，跳过 20 行");
    expect(status).toHaveTextContent("7 条坐标缺失");
    expect(status).toHaveTextContent("来源 EPSG:4326 → 存储 EPSG:4326（未转换）");
    // Dialog stays open while the report is visible; close is manual.
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();
  });

  it("surfaces CRS conversion warnings in the report", async () => {
    const summary = {
      message: "成功导入 1 个要素；坐标已从 EPSG:32650 转换为 EPSG:4326。",
      layer: { name: "utm", metadata: { source_crs: "EPSG:32650", stored_crs: "EPSG:4326", crs_converted: true } },
      crs: {
        source_crs: "EPSG:32650",
        target_crs: "EPSG:4326",
        reprojected: true,
        warnings: [{ code: "REPROJECTION_SUSPECT", message_zh: "坐标转换后仍有 1 组坐标超出经纬度范围，请核对。" }]
      },
      feature_report: { total_features: 1, imported_features: 1, skipped_features: 0, skip_reasons: {} }
    };
    const onSubmit = vi.fn().mockResolvedValue(summary);
    render(<UploadDialog open busy={false} onClose={() => {}} onSubmit={onSubmit} />);
    pickFile("utm.geojson");
    fireEvent.click(screen.getByRole("button", { name: "导入到课堂" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("坐标已从 EPSG:32650 转换为 EPSG:4326");
    expect(status).toHaveTextContent("已完成转换");
    expect(status).toHaveTextContent("坐标转换后仍有 1 组坐标超出经纬度范围");
  });
});
