import Link from 'next/link';
import { ArrowLeftIcon } from '@phosphor-icons/react/dist/ssr';
import { SettingsForm } from '@/components/app/settings-form';

export default function SettingsPage() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-12">
      <div>
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
        >
          <ArrowLeftIcon weight="bold" className="size-4" />
          Back
        </Link>
        <h1 className="mt-3 text-xl font-semibold">Settings</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Change the speech recognition, language model, and voice used by the assistant. A change
          restarts only the services it affects — the rest of the stack keeps running.
        </p>
      </div>
      <SettingsForm />
    </main>
  );
}
