import { createApiClient } from "./client.js";

const api = createApiClient();

export const LibrariesAPI = {
  list({ limit = 50, offset = 0 } = {}) {
    return api.get(`/libraries?limit=${limit}&offset=${offset}`);
  },

  roots(libraryId, { limit = 50, offset = 0 } = {}) {
    return api.get(`/libraries/${libraryId}/roots?limit=${limit}&offset=${offset}`);
  },

  addRoot(libraryId, { root_path, recursive = true }) {
    return api.post(`/libraries/${libraryId}/roots`, { root_path, recursive });
  },

  removeRoot(rootId) {
    return api.del(`/library-roots/${rootId}`);
  },

  recentlyAdded(libraryId, { limit = 50, offset = 0 } = {}) {
    return api.get(`/libraries/${libraryId}/recently-added?limit=${limit}&offset=${offset}`);
  },

  scan({ engine = "simple", dry_run = false, extensions = null } = {}) {
    return api.post(`/scan`, { engine, dry_run, extensions });
  },
};