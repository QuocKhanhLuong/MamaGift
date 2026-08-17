import { setupServer } from "msw/node";

/** Shared MSW server; individual tests register handlers with `server.use(...)`. */
export const server = setupServer();
