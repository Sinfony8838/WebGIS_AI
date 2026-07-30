import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BrandLogo } from "../components/BrandLogo";

describe("BrandLogo", () => {
  afterEach(cleanup);

  it("renders the shared platform image asset", () => {
    const { container } = render(<BrandLogo className="test-brand-logo" />);
    const image = container.querySelector("img");

    expect(image).toHaveClass("geobot-brand-logo", "test-brand-logo");
    expect(image?.getAttribute("src")).toContain("geobot-platform-logo.png");
    expect(image).toHaveAttribute("draggable", "false");
  });
});
