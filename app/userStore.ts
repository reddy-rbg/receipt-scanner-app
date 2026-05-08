// Simple global store for user token
let _token = '';

export function setUserToken(token: string) { _token = token; }
export function getUserToken(): string { return _token; }