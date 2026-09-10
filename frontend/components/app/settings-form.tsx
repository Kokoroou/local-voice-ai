'use client';

import { useEffect, useState } from 'react';
import { CheckIcon, SpinnerIcon, WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { CHILD_LABELS } from '@/components/app/welcome-view';
import { Alert, AlertDescription, AlertTitle } from '@/components/livekit/alert';
import { Button } from '@/components/livekit/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/livekit/card';
import { Input } from '@/components/livekit/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/livekit/select';
import { Toggle } from '@/components/livekit/toggle';
import { type ConfigChanges, useConfig } from '@/hooks/useConfig';
import { useStackStatus } from '@/hooks/useStackStatus';
import { cn } from '@/lib/utils';

type AdvancedFields = {
  sttProvider: string;
  sttLanguage: string;
  llamaHfRepo: string;
  llamaCtxSize: string;
  ttsProvider: string;
  ttsVoice: string;
  wakeWord: boolean;
  wakeWordThreshold: string;
  turnDetection: string;
};

function RestartProgress({ names }: { names: string[] }) {
  const status = useStackStatus();
  if (names.length === 0) return null;

  const relevant = status.children.filter((c) => names.includes(c.name));
  return (
    <div className="bg-muted/50 rounded-lg border p-3">
      <p className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
        Applying
      </p>
      <ul className="space-y-1.5">
        {relevant.map((child) => (
          <li key={child.name} className="flex items-center gap-2 text-sm">
            {child.ready ? (
              <CheckIcon weight="bold" className="size-4" />
            ) : (
              <SpinnerIcon weight="bold" className="text-muted-foreground size-4 animate-spin" />
            )}
            <span className={child.ready ? '' : 'text-muted-foreground'}>
              {CHILD_LABELS[child.name] ?? child.name}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SettingsForm() {
  const { snapshot, loading, saving, error, restarting, save } = useConfig();
  const [profileChoice, setProfileChoice] = useState<string>('');
  const [advanced, setAdvanced] = useState<AdvancedFields | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Seed local form state from the loaded snapshot, once, so edits aren't
  // clobbered by a refresh() triggered by an unrelated save.
  useEffect(() => {
    if (!snapshot || advanced) return;
    setAdvanced({
      sttProvider: snapshot.current.stt_provider,
      sttLanguage: snapshot.current.stt_language,
      llamaHfRepo: snapshot.current.llama_hf_repo,
      llamaCtxSize: String(snapshot.current.llama_ctx_size),
      ttsProvider: snapshot.current.tts_provider,
      ttsVoice: snapshot.current.tts_voice,
      wakeWord: snapshot.current.wake_word,
      wakeWordThreshold: String(snapshot.current.wake_word_threshold),
      turnDetection: snapshot.current.turn_detection,
    });
  }, [snapshot, advanced]);

  if (loading && !snapshot) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <SpinnerIcon weight="bold" className="size-4 animate-spin" />
        Loading settings…
      </div>
    );
  }

  if (!snapshot || !advanced) {
    return (
      <Alert variant="destructive">
        <WarningIcon weight="bold" />
        <AlertTitle>Couldn&apos;t load settings</AlertTitle>
        <AlertDescription>{error ?? 'Unknown error'}</AlertDescription>
      </Alert>
    );
  }

  const applyProfile = async (key: string) => {
    setProfileChoice(key);
    const ok = await save({ profile: key });
    if (!ok) setProfileChoice('');
  };

  const applyAdvanced = async () => {
    const changes: ConfigChanges = {
      STT_PROVIDER: advanced.sttProvider,
      STT_LANGUAGE: advanced.sttLanguage,
      LLAMA_HF_REPO: advanced.llamaHfRepo,
      LLAMA_CTX_SIZE: advanced.llamaCtxSize,
      TTS_PROVIDER: advanced.ttsProvider,
      TTS_VOICE: advanced.ttsVoice,
      WAKE_WORD: advanced.wakeWord ? '1' : '0',
      WAKE_WORD_THRESHOLD: advanced.wakeWordThreshold,
      TURN_DETECTION: advanced.turnDetection,
    };
    await save(changes);
  };

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <Alert variant="destructive">
          <WarningIcon weight="bold" />
          <AlertTitle>Couldn&apos;t save settings</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <RestartProgress names={restarting} />

      <Card>
        <CardHeader>
          <CardTitle>Model profile</CardTitle>
          <CardDescription>
            A tested LLM + speech recognition + voice combination for your hardware (
            {snapshot.platform_key}).
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {snapshot.profiles.map((profile) => (
            <button
              key={profile.key}
              type="button"
              disabled={!profile.supported || saving}
              onClick={() => applyProfile(profile.key)}
              className={cn(
                'flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors',
                profile.supported
                  ? 'hover:bg-accent cursor-pointer'
                  : 'cursor-not-allowed opacity-40',
                profileChoice === profile.key && saving && 'bg-accent'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{profile.label}</span>
                <span className="text-muted-foreground font-mono text-xs tabular-nums">
                  ~{profile.target_memory_gib} GB
                </span>
              </div>
              <p className="text-muted-foreground text-xs">{profile.description}</p>
              <p className="text-muted-foreground font-mono text-xs">
                {profile.llm} · {profile.stt} · {profile.tts}
              </p>
              {!profile.supported && (
                <p className="text-xs">Not available on this hardware/platform.</p>
              )}
            </button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Advanced</CardTitle>
              <CardDescription>Set STT/LLM/TTS fields individually.</CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? 'Hide' : 'Show'}
            </Button>
          </div>
        </CardHeader>
        {showAdvanced && (
          <CardContent className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Speech recognition provider">
                <Select
                  value={advanced.sttProvider}
                  onValueChange={(v) => setAdvanced({ ...advanced, sttProvider: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="nemotron-cpp">Nemotron (native streaming)</SelectItem>
                    <SelectItem value="whisper">Whisper</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field label="Speech language">
                <Input
                  value={advanced.sttLanguage}
                  onChange={(e) => setAdvanced({ ...advanced, sttLanguage: e.target.value })}
                  placeholder="en, fr-FR, auto…"
                />
              </Field>

              <Field label="Language model (HF repo:quant)">
                <Input
                  value={advanced.llamaHfRepo}
                  onChange={(e) => setAdvanced({ ...advanced, llamaHfRepo: e.target.value })}
                  placeholder="org/repo:QUANT"
                  className="font-mono text-xs"
                />
              </Field>

              <Field label="Context size">
                <Input
                  type="number"
                  min={512}
                  step={512}
                  value={advanced.llamaCtxSize}
                  onChange={(e) => setAdvanced({ ...advanced, llamaCtxSize: e.target.value })}
                />
              </Field>

              <Field label="Voice provider">
                <Select
                  value={advanced.ttsProvider}
                  onValueChange={(v) => setAdvanced({ ...advanced, ttsProvider: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="kokoro">Kokoro</SelectItem>
                    <SelectItem value="kokoro-onnx">Kokoro (ONNX, lower memory)</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field label="Voice">
                <Input
                  value={advanced.ttsVoice}
                  onChange={(e) => setAdvanced({ ...advanced, ttsVoice: e.target.value })}
                  placeholder="af_nova…"
                />
              </Field>

              <Field label="Turn detection">
                <Select
                  value={advanced.turnDetection}
                  onValueChange={(v) => setAdvanced({ ...advanced, turnDetection: v })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="multilingual">Multilingual (semantic)</SelectItem>
                    <SelectItem value="vad">VAD only</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field label="Wake word">
                <div className="flex items-center gap-3">
                  <Toggle
                    pressed={advanced.wakeWord}
                    onPressedChange={(v) => setAdvanced({ ...advanced, wakeWord: v })}
                    variant="outline"
                  >
                    {advanced.wakeWord ? 'On — "Hey LiveKit"' : 'Off'}
                  </Toggle>
                  {advanced.wakeWord && (
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={advanced.wakeWordThreshold}
                      onChange={(e) =>
                        setAdvanced({ ...advanced, wakeWordThreshold: e.target.value })
                      }
                      className="w-24"
                    />
                  )}
                </div>
              </Field>
            </div>

            <div>
              <Button type="button" variant="primary" disabled={saving} onClick={applyAdvanced}>
                {saving ? 'Applying…' : 'Apply advanced settings'}
              </Button>
            </div>
          </CardContent>
        )}
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-muted-foreground text-xs font-medium">{label}</span>
      {children}
    </label>
  );
}
