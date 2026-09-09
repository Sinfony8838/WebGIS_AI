import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// OpenLayers builds a real Map on mount, which jsdom cannot render. Replace
// every OL class with a proxy that returns itself for any method call, and
// the proj/sphere/easing/extent helpers with inert defaults. Defined via
// vi.hoisted so the values exist when the hoisted vi.mock factories run.
const { olProxy, olClass } = vi.hoisted(() => {
  const handler: ProxyHandler<Record<string | symbol, unknown>> = {
    get: (_target, prop) => {
      if (prop === "then") return undefined;
      if (prop === Symbol.toPrimitive) return () => 0;
      return (..._args: unknown[]) => olProxy;
    }
  };
  const olProxy = new Proxy({}, handler);
  function olClass() {
    return class {
      constructor(..._args: unknown[]) {
        return olProxy;
      }
    };
  }
  return { olProxy, olClass };
});

vi.mock("ol/Map", () => ({ default: olClass() }));
vi.mock("ol/View", () => ({ default: olClass() }));
vi.mock("ol/Feature", () => ({ default: olClass() }));
vi.mock("ol/format/GeoJSON", () => ({ default: olClass() }));
vi.mock("ol/interaction/Draw", () => ({ default: olClass() }));
vi.mock("ol/layer/Graticule", () => ({ default: olClass() }));
vi.mock("ol/layer/Image", () => ({ default: olClass() }));
vi.mock("ol/layer/Tile", () => ({ default: olClass() }));
vi.mock("ol/layer/Vector", () => ({ default: olClass() }));
vi.mock("ol/source/ImageStatic", () => ({ default: olClass() }));
vi.mock("ol/source/Vector", () => ({ default: olClass() }));
vi.mock("ol/source/XYZ", () => ({ default: olClass() }));
vi.mock("ol/geom/LineString", () => ({ default: olClass() }));
vi.mock("ol/geom/Point", () => ({ default: olClass() }));
vi.mock("ol/proj", () => ({
  fromLonLat: vi.fn((coord: number[]) => coord),
  toLonLat: vi.fn(() => [0, 0]),
  transformExtent: vi.fn((extent: number[]) => extent)
}));
vi.mock("ol/sphere", () => ({ getDistance: vi.fn(() => 0), getLength: vi.fn(() => 0) }));
vi.mock("ol/easing", () => ({ easeOut: vi.fn(() => (t: number) => t) }));
vi.mock("ol/extent", () => ({ getCenter: vi.fn(() => [0, 0]) }));
vi.mock("ol/Observable", () => ({ unByKey: vi.fn(() => undefined) }));
vi.mock("ol/style", () => ({
  Circle: olClass(),
  Fill: olClass(),
  RegularShape: olClass(),
  Stroke: olClass(),
  Style: olClass(),
  Text: olClass()
}));

// Cesium needs WebGL, unavailable in jsdom. globeRef is only read through
// optional chaining, so a null-returning forwardRef stub is safe.
vi.mock("../components/Map3DGlobe", async () => {
  const { forwardRef } = await import("react");
  return { Map3DGlobe: forwardRef(() => null) };
});

// LessonWorkflowShell runs its own backend effects on mount; stub it so the
// account-dock structural test stays focused on App's own JSX.
vi.mock("../components/LessonWorkflowShell", () => ({
  LessonWorkflowShell: () => null
}));

// MapBrushOverlay is always mounted by App and needs a canvas 2D context; it is
// irrelevant to the account dock, so stub it. All brush ref usage in App
// goes through optional chaining, so a null ref is safe.
vi.mock("../components/MapBrushOverlay", async () => {
  const { forwardRef } = await import("react");
  return { MapBrushOverlay: forwardRef(() => null) };
});

// Let the init effect fail fast at fetchHealth so no project / layer state is
// created and the project-gated map effects never run. The account dock
// renders regardless of init state.
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchHealth: vi.fn().mockRejectedValue(new Error("backend unavailable")),
    fetchCurrentUser: vi.fn().mockResolvedValue(undefined)
  };
});

import App from "../App";
import type { AuthUser } from "../types";

const admin: AuthUser = {
  user_id: "user_admin",
  email: "admin@school.edu.cn",
  nickname: "系统管理员",
  role: "admin",
  status: "active",
  must_change_password: false,
  created_at: "",
  updated_at: "",
  last_login_at: "",
  locked_until: ""
};

describe("account dock", () => {
  beforeEach(() => {
    // App's map-init effect constructs a ResizeObserver on the map container;
    // jsdom does not provide one.
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("mounts the user menu inside a bottom-left account dock and removes it from header-actions", async () => {
    render(<App currentUser={admin} onLogout={vi.fn()} onUserChanged={vi.fn()} />);

    const dock = await screen.findByTestId("account-dock");
    expect(dock).toBeInTheDocument();
    expect(dock.querySelector(".user-menu")).not.toBeNull();
    expect(dock.querySelector(".user-menu-trigger")).not.toBeNull();

    const headerActions = document.querySelector(".header-actions");
    expect(headerActions).not.toBeNull();
    expect(headerActions?.querySelector(".user-menu")).toBeNull();
    expect(headerActions?.querySelector(".user-menu-trigger")).toBeNull();
  });

  it("opens the account menu when the dock card is clicked", async () => {
    render(<App currentUser={admin} onLogout={vi.fn()} onUserChanged={vi.fn()} />);

    const dock = await screen.findByTestId("account-dock");
    const trigger = dock.querySelector(".user-menu-trigger") as HTMLButtonElement;
    expect(trigger).not.toBeNull();

    expect(screen.queryByText(admin.email)).not.toBeInTheDocument();
    fireEvent.click(trigger);
    await waitFor(() => {
      expect(screen.getByText(admin.email)).toBeInTheDocument();
    });
    expect(screen.getByRole("menuitem", { name: "用户管理" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "修改密码" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeInTheDocument();
  });
});
