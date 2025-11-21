export type TokenProvider = (() => Promise<string | undefined>) | (() => string | undefined);

let provider: TokenProvider | null = null;

export const setAuthTokenProvider = (fn: TokenProvider | null) => {
    provider = fn;
};

export const resolveAuthToken = async () => {
    if (!provider) {
        return undefined;
    }
    const result = provider();
    return result instanceof Promise ? result : await Promise.resolve(result);
};
