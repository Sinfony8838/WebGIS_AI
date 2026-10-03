import JSZip from "jszip";
import { afterEach, expect, it, vi } from "vitest";
import { parsePptxFile, releaseSlideObjectUrls } from "../lib/pptxRenderer";

afterEach(() => vi.restoreAllMocks());
it("resolves relative images and relationship attributes regardless of order, follows deck order, and escapes slide text", async () => {
  const zip = new JSZip();
  zip.file("ppt/presentation.xml", '<p:presentation xmlns:p="urn:p" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldSz cx="9144000" cy="5143500"/><p:sldIdLst><p:sldId r:id="second"/><p:sldId r:id="first"/></p:sldIdLst></p:presentation>');
  zip.file("ppt/_rels/presentation.xml.rels", '<Relationships><Relationship Target="slides/slide2.xml" Id="second" Type="urn:test/slide"/><Relationship Target="slides/slide1.xml" Id="first" Type="urn:test/slide"/></Relationships>');
  const xfrm = '<a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm>';
  zip.file("ppt/slides/slide1.xml", `<p:spTree><p:sp><p:spPr>${xfrm}</p:spPr><p:txBody><a:p><a:r><a:rPr sz="2000"><a:solidFill><a:srgbClr val="AA2211"/></a:solidFill></a:rPr><a:t>&lt;img src=x onerror=alert(1)&gt;</a:t></a:r></a:p></p:txBody></p:sp></p:spTree>`);
  zip.file("ppt/slides/slide2.xml", `<p:spTree><p:pic><p:spPr>${xfrm}</p:spPr><a:blip r:embed="photo"/></p:pic></p:spTree>`);
  zip.file("ppt/slides/_rels/slide2.xml.rels", '<Relationships><Relationship Target="../media/image1.png" Type="urn:test/image" Id="photo"/><Relationship Id="remote" Type="urn:test/image" Target="https://example.com/private.png" TargetMode="External"/></Relationships>');
  zip.file("ppt/media/image1.png", new Uint8Array([1, 2, 3]));
  const create = vi.fn(() => "blob:test"); const revoke = vi.fn();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
  const bytes = await zip.generateAsync({ type: "arraybuffer" });
  const parsed = await parsePptxFile({ name: "sample.pptx", arrayBuffer: async () => bytes } as File);
  expect(parsed.slides[0].html).toContain('src="blob:test"');
  expect(parsed.slides[0].images).toEqual({ photo: "blob:test" });
  expect(parsed.slides[1].html).toContain("color:#AA2211");
  expect(parsed.slides[1].html).toContain("&lt;img");
  const element = document.createElement("div"); element.innerHTML = parsed.slides[1].html;
  expect(element.querySelector("img")).toBeNull();
  releaseSlideObjectUrls(parsed.slides); expect(revoke).toHaveBeenCalledWith("blob:test");
  vi.unstubAllGlobals();
});
