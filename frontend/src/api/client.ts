import axios from 'axios';
import {resolveAuthToken} from './authToken';

const normalizeBase = (url: string) => {
    if (url === '/') {
        return '/';
    }
    return url.endsWith('/') ? url.slice(0, -1) : url;
};

const baseURL = normalizeBase(import.meta.env.VITE_API_URL ?? '/api');

export const apiClient = axios.create({
    baseURL,
});

apiClient.interceptors.request.use(async (config) => {
    const token = await resolveAuthToken();
    if (token) {
        config.headers = config.headers ?? {};
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        const message =
            error?.response?.data?.message ??
            error?.message ??
            'Something went wrong';
        return Promise.reject(new Error(message));
    },
);
