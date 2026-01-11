import { createApiClient } from "./client.js";

const api = createApiClient();
const USER_ID = 1; // no auth yet; single admin user.

export const PlaybackAPI = {
  continueWatching({ limit = 50, offset = 0 } = {}) {
    return api.get(`/users/${USER_ID}/continue-watching?limit=${limit}&offset=${offset}`);
  },

  // Client may omit "completed" so server computes it.
  progress({ media_file_id, position_seconds, duration_seconds, completed = undefined }) {
    const payload = { media_file_id, position_seconds, duration_seconds };
    if (typeof completed === "boolean") payload.completed = completed;
    return api.post(`/users/${USER_ID}/progress`, payload);
  },
};