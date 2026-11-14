import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// @testing-library/react only auto-cleans when the test runner exposes
// globals; vitest does not by default, so unmount after every test.
afterEach(() => {
  cleanup();
});
