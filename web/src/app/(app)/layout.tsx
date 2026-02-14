import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { SyncUser } from "@/components/sync-user";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      <SyncUser />
      <header className="border-b border-border h-11 px-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-5">
          <Link
            href="/dashboard"
            className="font-mono font-bold text-xs tracking-tight text-foreground hover:text-foreground/80 transition-colors"
          >
            RE:ZERO
          </Link>
          <div className="w-px h-4 bg-border" />
          <nav className="flex items-center gap-3 text-xs font-mono text-muted-foreground">
            <Link
              href="/dashboard"
              className="hover:text-foreground transition-colors"
            >
              projects
            </Link>
            <Link
              href="/projects/new"
              className="hover:text-foreground transition-colors"
            >
              new
            </Link>
          </nav>
        </div>
        <UserButton
          appearance={{
            elements: {
              avatarBox: "h-6 w-6",
            },
          }}
        />
      </header>
      <main className="flex-1 px-4 py-4">{children}</main>
    </div>
  );
}
