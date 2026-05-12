import { create } from 'zustand';
interface UserTokenState { token: string | null; setToken: (token: string | null) => void; clearToken: () => void; }
export const useUserStore = create<UserTokenState>((set)=>({ token:null, setToken:(token)=>set({token}), clearToken:()=>set({token:null}) }));
export default useUserStore;
