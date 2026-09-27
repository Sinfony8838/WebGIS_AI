import JSZip from "jszip";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parsePptxFile, releaseSlideObjectUrls, resolvePptRelPath } from "../lib/pptxRenderer";

const FAKE_PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function buildPptxXml(options: { relsXml: string; slideBody: string }): { files: Record<string, string | Uint8Array> } {
  return {
    files: {
      "[Content_Types].xml": "<?xml version=\"1.0\"?><Types/>",
      "ppt/presentation.xml":
        '<p:presentation xmlns:p="x"><p:sldSz cx="12192000" cy="6858000"/></p:presentation>',
      "ppt/slides/slide1.xml":
        '<p:sld xmlns:p="x" xmlns:a="y" xmlns:r="z"><p:cSld><p:spTree>'
        + options.slideBody
        + "</p:spTree></p:cSld></p:sld>",
      "ppt/slides/_rels/slide1.xml.rels": options.relsXml,
      "ppt/media/image1.png": FAKE_PNG
    }
  };
}

async function parseFixture(relsXml: string, slideBody: string) {
  const zip = new JSZip();
  const files = buildPptxXml({ relsXml, slideBody }).files;
  for (const [path, content] of Object.entries(files)) {
    zip.file(path, content);
  }
  const bytes = await zip.generateAsync({ type: "uint8array" });
  const file = new File([bytes], "deck.pptx", { type: "application/vnd.openxmlformats-officedocument.presentationml.presentation" });
  // jsdom's Blob polyfill lacks arrayBuffer(); parsePptxFile only needs the bytes.
  (file as File & { arrayBuffer: () => Promise<ArrayBuffer> }).arrayBuffer = () =>
    Promise.resolve(bytes.slice().buffer as ArrayBuffer);
  return parsePptxFile(file);
}

describe("pptxRenderer simple parser", () => {
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;

  beforeEach(() => {
    // jsdom does not implement blob object URLs.
    URL.createObjectURL = vi.fn(
      () => `blob:mock-${Math.random().toString(36).slice(2)}`
    ) as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.restoreAllMocks();
  });

  it("resolves ../media/ relationship targets to real zip entries", async () => {
    const relsXml =
      '<?xml version="1.0"?><Relationships>'
      + '<Relationship Target="../media/image1.png" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Id="rId2"/>'
      + "</Relationships>";
    const slideBody =
      '<p:pic><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="9144000" cy="6858000"/></a:xfrm></p:spPr>'
      + '<p:blipFill><a:blip r:embed="rId2"/></p:blipFill></p:pic>';
    const result = await parseFixture(relsXml, slideBody);
    expect(result.slides).toHaveLength(1);
    expect(Object.keys(result.slides[0].images)).toContain("rId2");
    expect(result.slides[0].html).toContain("<img");
    expect(result.mode).toBe("simple");
    releaseSlideObjectUrls(result.slides);
  });

  it("parses relationships regardless of attribute order", async () => {
    const relsXml =
      '<Relationships>'
      + '<Relationship Target="../media/image1.png" Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"/>'
      + "</Relationships>";
    const result = await parseFixture(relsXml, "");
    expect(Object.keys(result.slides[0].images)).toContain("rId9");
    releaseSlideObjectUrls(result.slides);
  });

  it("escapes text before injecting into slide HTML", async () => {
    const relsXml = "<Relationships/>";
    const slideBody =
      '<p:sp><p:spPr><a:xfrm><a:off x="10" y="10"/><a:ext cx="100" cy="40"/></a:xfrm></p:spPr>'
      + '<p:txBody><a:p><a:r><a:rPr lang="zh-CN"/><a:t>人口 &amp; &lt;迁移&gt;</a:t></a:r>'
      + '<a:r><a:rPr/><a:t>&lt;img src=x onerror=alert(1)&gt;</a:t></a:r></a:p></p:txBody></p:sp>';
    const result = await parseFixture(relsXml, slideBody);
    const html = result.slides[0].html;
    expect(html).toContain("人口 &amp; &lt;迁移&gt;");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).not.toContain("<img src=x");
    releaseSlideObjectUrls(result.slides);
  });

  it("keeps literal ampersand entity text intact (no double unescape)", async () => {
    const relsXml = "<Relationships/>";
    const slideBody =
      '<p:sp><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="10" cy="10"/></a:xfrm></p:spPr>'
      + '<p:txBody><a:p><a:r><a:rPr/><a:t>A &amp;amp; B</a:t></a:r></a:p></p:txBody></p:sp>';
    const result = await parseFixture(relsXml, slideBody);
    // XML "&amp;amp;" unescapes to "&amp;"; HTML-escaping renders it as "&amp;amp;".
    expect(result.slides[0].html).toContain("A &amp;amp; B");
    releaseSlideObjectUrls(result.slides);
  });

  it("maps slide-relative media targets without .. prefix", async () => {
    expect(resolvePptRelPath("../media/image1.png")).toBe("ppt/media/image1.png");
    expect(resolvePptRelPath("./media/image1.png")).toBe("ppt/slides/media/image1.png");
    expect(resolvePptRelPath("/ppt/media/image1.png")).toBe("ppt/media/image1.png");
    expect(resolvePptRelPath("../media/my%20image.png")).toBe("ppt/media/my image.png");
  });
});
