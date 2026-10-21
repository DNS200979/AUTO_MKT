import { createClient } from '@supabase/supabase-js'

const projectUrl = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// A sessão fica restrita à aba/sessão do navegador para a POC.
export const supabase = projectUrl && anonKey
  ? createClient(projectUrl, anonKey, {
      auth: {
        persistSession: true,
        storage: window.sessionStorage,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null
