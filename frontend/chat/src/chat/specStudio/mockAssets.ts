import { createContext } from "react";

/** The Corporate Identity's logo and icons (slug → address) for the mock; empty without a corporate direction. */
export type MockAssets = { logo?: string; icons: Record<string, string> };
export const MockAssetsContext = createContext<MockAssets>({ icons: {} });
