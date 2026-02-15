import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { SyncUser } from "@/components/sync-user";
import { ThemeToggle } from "@/components/theme-toggle";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <SyncUser />
      <header className="border-b border-border px-8 h-11 flex items-center justify-between shrink-0 mt-[2px]">
        <div className="flex items-center gap-8 text-sm">
          <Link href="/dashboard" className="tracking-tight hover:opacity-70 transition-opacity duration-150">
            <span className="font-semibold">re</span>
            <span className="text-destructive font-semibold">:</span>
            <span className="font-semibold">zero</span>
          </Link>
        </div>
        <div className="flex items-center gap-4">
          <ThemeToggle />
          <UserButton appearance={{ elements: { avatarBox: "h-5 w-5" } }} />
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
