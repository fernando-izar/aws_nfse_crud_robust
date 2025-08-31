import axios from "axios";
export const api = (baseURL: string, token?: string, apiKey?: string) => {
  const i = axios.create({ baseURL });
  i.interceptors.request.use((c) => {
    if (token) c.headers.Authorization = `Bearer ${token}`;
    if (apiKey) c.headers["x-api-key"] = apiKey;
    return c;
  });
  return i;
};
