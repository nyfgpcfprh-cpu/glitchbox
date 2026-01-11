import { createApiClient } from "./client.js";

const api = createApiClient();
const USER_ID = 1;

export const PlaylistsAPI = {
  list({ limit = 50, offset = 0 } = {}) {
    return api.get(`/users/${USER_ID}/playlists?limit=${limit}&offset=${offset}`);
  },

  create({ name }) {
    return api.post(`/users/${USER_ID}/playlists`, { name });
  },

  items(playlistId, { limit = 100, offset = 0 } = {}) {
    return api.get(`/playlists/${playlistId}/items?limit=${limit}&offset=${offset}`);
  },

  rename(playlistId, { name }) {
    return api.patch(`/playlists/${playlistId}`, { name });
  },

  delete(playlistId) {
    return api.del(`/playlists/${playlistId}`);
  },

  addItem(playlistId, { media_file_id }) {
    return api.post(`/playlists/${playlistId}/items`, { media_file_id });
  },

  removeItem(playlistId, playlist_item_id) {
    return api.del(`/playlists/${playlistId}/items/${playlist_item_id}`);
  },

  moveItem(playlistId, playlist_item_id, { new_position }) {
    return api.post(`/playlists/${playlistId}/items/${playlist_item_id}/move`, { new_position });
  },
};