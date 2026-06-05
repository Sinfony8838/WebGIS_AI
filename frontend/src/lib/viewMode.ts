/**
 * Shared type for the map view mode toggle. Lives in its own module so
 * components can import it without creating circular dependencies with
 * App.tsx or Map3DGlobe.tsx.
 */
export type ViewMode = "globe" | "plane";
