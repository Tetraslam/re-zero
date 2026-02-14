import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { SignInButton } from "@clerk/nextjs";
import { Button } from "@/components/ui/button";
import { Shield, Code, Cpu, Radio } from "lucide-react";

export default async function LandingPage() {
  const { userId } = await auth();

  if (userId) {
    redirect("/dashboard");
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="h-11 px-4 flex items-center border-b border-border">
        <span className="font-mono font-bold text-xs tracking-tight">
          RE:ZERO
        </span>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="max-w-2xl w-full space-y-12 text-center">
          {/* Hero */}
          <div className="space-y-4">
            <h1 className="text-5xl font-bold tracking-tighter font-mono">
              Re:Zero
            </h1>
            <p className="text-lg text-muted-foreground max-w-md mx-auto leading-relaxed">
              Autonomous red teaming that reverse engineers any attack surface.
              Code, web, hardware, FPGA.
            </p>
          </div>

          {/* CTA */}
          <SignInButton mode="modal">
            <Button size="lg" className="font-mono text-sm px-8">
              Start scanning
            </Button>
          </SignInButton>

          {/* Capabilities */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4">
            {[
              {
                icon: Code,
                label: "OSS Repos",
                desc: "Clone, analyze, report vulnerabilities",
              },
              {
                icon: Shield,
                label: "Web Apps",
                desc: "Browser-based penetration testing",
              },
              {
                icon: Cpu,
                label: "Hardware",
                desc: "ESP32, drones, serial protocols",
              },
              {
                icon: Radio,
                label: "FPGA",
                desc: "Side-channel analysis, glitching",
              },
            ].map((cap) => (
              <div
                key={cap.label}
                className="border border-border rounded-lg p-4 text-left space-y-2"
              >
                <cap.icon className="h-4 w-4 text-muted-foreground" />
                <div className="text-sm font-medium">{cap.label}</div>
                <div className="text-xs text-muted-foreground leading-relaxed">
                  {cap.desc}
                </div>
              </div>
            ))}
          </div>

          {/* Agents */}
          <div className="flex items-center justify-center gap-6 text-xs text-muted-foreground font-mono pt-2">
            <span>Opus 4.6</span>
            <span className="text-border">|</span>
            <span>GLM-4.7V</span>
            <span className="text-border">|</span>
            <span>Nemotron</span>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="h-11 px-4 flex items-center justify-center border-t border-border">
        <span className="text-xs text-muted-foreground font-mono">
          return from zero
        </span>
      </footer>
    </div>
  );
}
