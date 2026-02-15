import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { SignInButton } from "@clerk/nextjs";

export default async function LandingPage() {
  const { userId } = await auth();

  if (userId) {
    redirect("/dashboard");
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Brand line handled by body::before */}
      <header className="px-8 h-11 flex items-center justify-between border-b border-border mt-[2px]">
        <span className="text-sm">
          <span className="font-semibold">re</span>
          <span className="text-destructive font-semibold">:</span>
          <span className="font-semibold">zero</span>
        </span>
        <SignInButton mode="modal">
          <button className="text-sm text-muted-foreground hover:text-rem transition-colors duration-150">
            sign in
          </button>
        </SignInButton>
      </header>

      <main className="flex-1 flex flex-col">
        {/* Hero */}
        <section className="px-8 pt-24 pb-20 max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight leading-tight">
            Deploy Rem to red team<br />
            any attack surface.
          </h1>
          <p className="text-base text-muted-foreground mt-6 leading-relaxed max-w-xl">
            Point an autonomous AI agent at a codebase, web application, or hardware
            device. Rem reads, probes, and iterates — exploring the attack surface
            like a security researcher would, but at machine speed. You watch Rem
            think in real time. She hands you a structured report with findings,
            severity ratings, and remediation advice.
          </p>
          <div className="flex items-center gap-6 mt-8">
            <SignInButton mode="modal">
              <button className="text-sm bg-rem text-white px-5 py-2.5 hover:brightness-110 transition-all duration-150 active:translate-y-px">
                deploy Rem
              </button>
            </SignInButton>
            <span className="text-xs text-muted-foreground">
              autonomous security analysis in minutes, not weeks
            </span>
          </div>
        </section>

        <div className="border-t border-border" />

        {/* How it works */}
        <section className="px-8 py-16 max-w-3xl">
          <h2 className="text-xs text-muted-foreground mb-8">How it works</h2>
          <div className="space-y-6">
            <div className="flex gap-6">
              <span className="text-xs text-rem/60 w-4 shrink-0 pt-0.5 tabular-nums">1</span>
              <div>
                <div className="text-sm font-medium">Create a project</div>
                <div className="text-sm text-muted-foreground mt-1">
                  Point it at a GitHub repository, a live URL, a hardware device
                  over serial, or an FPGA target. Rem accepts any attack surface.
                </div>
              </div>
            </div>
            <div className="flex gap-6">
              <span className="text-xs text-rem/60 w-4 shrink-0 pt-0.5 tabular-nums">2</span>
              <div>
                <div className="text-sm font-medium">Deploy Rem</div>
                <div className="text-sm text-muted-foreground mt-1">
                  Choose a model backbone — Claude Opus, GLM-4.7V, or Nemotron.
                  Rem spins up in a sandboxed environment and begins autonomous
                  analysis. She reads files, searches for patterns, probes endpoints.
                </div>
              </div>
            </div>
            <div className="flex gap-6">
              <span className="text-xs text-rem/60 w-4 shrink-0 pt-0.5 tabular-nums">3</span>
              <div>
                <div className="text-sm font-medium">Watch Rem think</div>
                <div className="text-sm text-muted-foreground mt-1">
                  Trace Rem&apos;s reasoning, file reads, code searches, and
                  discoveries as they happen. Every action streams in real time.
                  You see the turns, the tools, the inner monologue.
                </div>
              </div>
            </div>
            <div className="flex gap-6">
              <span className="text-xs text-rem/60 w-4 shrink-0 pt-0.5 tabular-nums">4</span>
              <div>
                <div className="text-sm font-medium">Get a structured report</div>
                <div className="text-sm text-muted-foreground mt-1">
                  Each finding has a vulnerability ID (VN-001), severity rating,
                  file location, description, and remediation advice. Ready for
                  your security review. Run multiple scans, compare reports.
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="border-t border-border" />

        {/* Attack surfaces */}
        <section className="px-8 py-16">
          <h2 className="text-xs text-muted-foreground mb-8">Attack surfaces</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-12 gap-y-8 max-w-3xl">
            <div>
              <div className="text-sm font-medium">Source code</div>
              <div className="text-sm text-muted-foreground mt-1 leading-relaxed">
                Clone any public repo. Deep static analysis for injection,
                auth bypass, hardcoded secrets, logic flaws. Rem reads every
                file she deems relevant.
              </div>
            </div>
            <div>
              <div className="text-sm font-medium">Web apps</div>
              <div className="text-sm text-muted-foreground mt-1 leading-relaxed">
                Browser-based pentesting with full page interaction.
                XSS, CSRF, SSRF, IDOR, auth testing. Rem navigates,
                submits forms, and probes endpoints.
              </div>
            </div>
            <div>
              <div className="text-sm font-medium">Hardware</div>
              <div className="text-sm text-muted-foreground mt-1 leading-relaxed">
                ESP32, drones, serial protocols. Connect via gateway for
                firmware extraction and protocol fuzzing. Rem speaks
                UART, SPI, I2C.
              </div>
            </div>
            <div>
              <div className="text-sm font-medium">FPGA</div>
              <div className="text-sm text-muted-foreground mt-1 leading-relaxed">
                Side-channel analysis, voltage glitching, timing attacks.
                Extract secrets from hardware implementations. Rem
                controls the glitch parameters.
              </div>
            </div>
          </div>
        </section>

        <div className="border-t border-border" />

        {/* Models + CTA */}
        <section className="px-8 py-16 max-w-3xl">
          <h2 className="text-xs text-muted-foreground mb-6">Rem&apos;s model backbones</h2>
          <div className="flex items-baseline gap-8 text-sm">
            <span className="text-rem">Opus 4.6</span>
            <span className="text-rem/30">&middot;</span>
            <span className="text-rem">GLM-4.7V</span>
            <span className="text-rem/30">&middot;</span>
            <span className="text-rem">Nemotron</span>
          </div>
          <p className="text-sm text-muted-foreground mt-4 leading-relaxed max-w-lg">
            Each model brings different strengths. Opus excels at deep reasoning
            and multi-step analysis. GLM-4.7V adds vision for screenshot-based
            web testing. Nemotron is RL-optimized for CTF-style challenges.
            Deploy all three, compare their findings.
          </p>

          <div className="mt-10">
            <SignInButton mode="modal">
              <button className="text-sm bg-rem text-white px-5 py-2.5 hover:brightness-110 transition-all duration-150 active:translate-y-px">
                start scanning
              </button>
            </SignInButton>
          </div>
        </section>
      </main>

      <footer className="px-8 h-11 flex items-center border-t border-border">
        <span className="text-xs text-muted-foreground">return from zero</span>
      </footer>
    </div>
  );
}
