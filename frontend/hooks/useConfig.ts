'use client';

import { useCallback, useEffect, useState } from 'react';
import { getBackendUrl } from '@/lib/utils';

export interface ProfileOption {
  key: string;
  label: string;
  description: string;
  llm: string;
  stt: string;
  tts: string;
  target_memory_gib: number;
  download_gib: number;
  supported: boolean;
}

export interface CurrentSettings {
  stt_provider: string;
  stt_language: string;
  tts_provider: string;
  tts_voice: string;
  llama_hf_repo: string;
  llama_model: string;
  llama_ctx_size: number;
  wake_word: boolean;
  wake_word_threshold: number;
  turn_detection: string;
}

export interface ConfigSnapshot {
  current: CurrentSettings;
  platform_key: string;
  profiles: ProfileOption[];
}

/** Values POSTed to /api/config: either {profile} or whitelisted advanced fields. */
export type ConfigChanges = Record<string, string>;

interface UseConfigResult {
  snapshot: ConfigSnapshot | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  /** Child names the backend is restarting after the last successful save. */
  restarting: string[];
  refresh: () => Promise<void>;
  save: (changes: ConfigChanges) => Promise<boolean>;
}

/**
 * Loads /api/config and applies changes to it. Mirrors useStackStatus's
 * fetch pattern — no shared HTTP wrapper exists in this codebase, so this
 * stays consistent with the one other hook that talks to the backend.
 */
export function useConfig(): UseConfigResult {
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(getBackendUrl('/api/config'), { cache: 'no-store' });
      if (!res.ok) throw new Error(`status ${res.status}`);
      setSnapshot(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to load settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const save = useCallback(
    async (changes: ConfigChanges) => {
      setSaving(true);
      setError(null);
      try {
        const res = await fetch(getBackendUrl('/api/config'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(changes),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof data.detail === 'string' ? data.detail : `status ${res.status}`);
        }
        setRestarting(Array.isArray(data.restarting) ? data.restarting : []);
        await refresh();
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'failed to save settings');
        return false;
      } finally {
        setSaving(false);
      }
    },
    [refresh]
  );

  return { snapshot, loading, saving, error, restarting, refresh, save };
}
