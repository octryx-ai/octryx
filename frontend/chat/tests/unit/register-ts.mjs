// Resolves extensionless relative imports inside src/ to their `.ts` source so
// Node's built-in type stripping can load pure frontend modules in unit tests.
import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[cm]?[jt]sx?$/.test(specifier)) {
      try {
        return nextResolve(`${specifier}.ts`, context);
      } catch {
        // Fall through to default resolution.
      }
    }
    return nextResolve(specifier, context);
  },
});
