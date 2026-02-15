"use client";

import { useEffect, useRef, useState } from "react";
import { SignInButton } from "@clerk/nextjs";
import dynamic from "next/dynamic";

const Dithering = dynamic(
  () => import("@paper-design/shaders-react").then((m) => m.Dithering),
  { ssr: false }
);

export function LandingContent() {
  const root = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted || !root.current) return;

    let scope: { revert: () => void } | null = null;

    (async () => {
      const { createScope, animate, stagger, splitText, createTimeline } =
        await import("animejs");

      scope = createScope({ root }).add(() => {
        // Title character reveal
        const { chars } = splitText(".hero-title", { chars: true });

        const tl = createTimeline({
          defaults: { ease: "outExpo" },
        });

        tl.add(chars, {
          opacity: [0, 1],
          translateY: ["2rem", "0rem"],
          delay: stagger(35),
          duration: 900,
        })
          .add(
            ".hero-tagline",
            {
              opacity: [0, 1],
              translateY: ["1.5rem", "0rem"],
              duration: 1000,
            },
            "-=500"
          )
          .add(
            ".hero-cta",
            {
              opacity: [0, 1],
              translateY: ["1rem", "0rem"],
              duration: 800,
            },
            "-=600"
          );

        // Gif entrance
        animate(".hero-gif-wrap", {
          opacity: [0, 1],
          scale: [1.04, 1],
          duration: 1400,
          ease: "outExpo",
          delay: 100,
        });

        // Sections stagger in on load (below fold — they animate when scrolled to)
        animate(".reveal-item", {
          opacity: [0, 1],
          translateY: ["2.5rem", "0rem"],
          delay: stagger(80),
          duration: 900,
          ease: "outExpo",
        });

        // Step numbers count
        animate(".step-num", {
          opacity: [0, 1],
          scale: [0.5, 1],
          delay: stagger(120, { start: 600 }),
          duration: 600,
          ease: "outExpo",
        });
      });
    })();

    return () => scope?.revert();
  }, [mounted]);

  return (
    <div ref={root} className="flex min-h-screen flex-col">
      {/* ── Hero ─────────────────────────────────────────── */}
      <section className="relative min-h-screen flex flex-col">
        {/* Animated dithering background */}
        {mounted && (
          <div className="absolute inset-0 z-0 overflow-hidden">
            <Dithering
              colorBack="var(--color-background, #f7f7fc)"
              colorFront="var(--color-rem, #4f68e8)"
              shape="simplex"
              type="4x4"
              size={2}
              speed={0.15}
              scale={0.8}
              style={{
                width: "100%",
                height: "100%",
                opacity: 0.04,
              }}
            />
          </div>
        )}

        {/* Header */}
        <header className="relative z-10 px-8 h-11 flex items-center justify-between border-b border-border mt-[2px]">
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

        {/* Hero content */}
        <div className="relative z-10 flex-1 flex flex-col items-center justify-center px-8 pb-16">
          {/* Rem gif — the star */}
          <div className="hero-gif-wrap relative w-full max-w-[720px] aspect-[500/281] mb-10 opacity-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/rem-hero.gif"
              alt="Rem"
              className="w-full h-full object-cover"
              style={{ imageRendering: "auto" }}
            />
            {/* Dithering overlay on gif */}
            {mounted && (
              <div
                className="absolute inset-0 pointer-events-none"
                style={{ mixBlendMode: "overlay", opacity: 0.12 }}
              >
                <Dithering
                  colorBack="#000000"
                  colorFront="#ffffff"
                  shape="simplex"
                  type="4x4"
                  size={2}
                  speed={0.2}
                  scale={1.2}
                  style={{ width: "100%", height: "100%" }}
                />
              </div>
            )}
            {/* Border frame */}
            <div className="absolute inset-0 border border-border pointer-events-none" />
          </div>

          {/* Title */}
          <h1 className="hero-title text-5xl sm:text-6xl md:text-7xl font-semibold tracking-tight text-center leading-none">
            <span>re</span>
            <span className="text-destructive">:</span>
            <span>zero</span>
          </h1>

          {/* Tagline */}
          <p className="hero-tagline text-lg sm:text-xl text-muted-foreground mt-6 text-center max-w-xl leading-relaxed opacity-0">
            deploy Rem to red team any attack surface.
            <br />
            <span className="text-sm text-muted-foreground/60">
              autonomous security analysis in minutes, not weeks.
            </span>
          </p>

          {/* CTA */}
          <div className="hero-cta mt-10 opacity-0">
            <SignInButton mode="modal">
              <button className="text-sm bg-rem text-white px-8 py-3 hover:brightness-110 transition-all duration-150 active:translate-y-px">
                deploy Rem
              </button>
            </SignInButton>
          </div>
        </div>

        {/* Scroll hint */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
          <div className="w-px h-8 bg-border animate-pulse" />
        </div>
      </section>

      <div className="border-t border-border" />

      {/* ── How it works ─────────────────────────────────── */}
      <section className="px-8 py-20 max-w-5xl mx-auto w-full">
        <h2 className="text-xs text-muted-foreground mb-12 reveal-item opacity-0">
          How it works
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10">
          {[
            {
              n: "01",
              title: "Create a project",
              desc: "Point it at a GitHub repo, a live URL, a hardware device, or an FPGA target. Rem accepts any attack surface.",
            },
            {
              n: "02",
              title: "Deploy Rem",
              desc: "Choose a model backbone. Rem spins up in a sandboxed environment and begins autonomous analysis.",
            },
            {
              n: "03",
              title: "Watch Rem think",
              desc: "Trace reasoning, file reads, code searches, and discoveries as they happen. Every action streams in real time.",
            },
            {
              n: "04",
              title: "Get a report",
              desc: "Each finding has a vulnerability ID, severity rating, location, and remediation advice. Ready for your review.",
            },
          ].map((step) => (
            <div key={step.n} className="reveal-item opacity-0">
              <span className="step-num text-3xl font-semibold text-rem/20 tabular-nums opacity-0">
                {step.n}
              </span>
              <div className="text-sm font-medium mt-3">{step.title}</div>
              <div className="text-sm text-muted-foreground mt-2 leading-relaxed">
                {step.desc}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="border-t border-border" />

      {/* ── Attack surfaces ──────────────────────────────── */}
      <section className="px-8 py-20 max-w-5xl mx-auto w-full">
        <h2 className="text-xs text-muted-foreground mb-12 reveal-item opacity-0">
          Attack surfaces
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10">
          {[
            {
              title: "Source code",
              desc: "Clone any repo. Deep static analysis for injection, auth bypass, hardcoded secrets, logic flaws.",
            },
            {
              title: "Web apps",
              desc: "Browser-based pentesting with full page interaction. XSS, CSRF, SSRF, IDOR, auth testing.",
            },
            {
              title: "Hardware",
              desc: "ESP32, drones, serial protocols. Firmware extraction and protocol fuzzing over UART, SPI, I2C.",
            },
            {
              title: "FPGA",
              desc: "Side-channel analysis, voltage glitching, timing attacks. Extract secrets from hardware implementations.",
            },
          ].map((surface) => (
            <div
              key={surface.title}
              className="reveal-item opacity-0 border-l-2 border-l-rem/20 pl-4"
            >
              <div className="text-sm font-medium">{surface.title}</div>
              <div className="text-sm text-muted-foreground mt-2 leading-relaxed">
                {surface.desc}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="border-t border-border" />

      {/* ── Models + Final CTA ───────────────────────────── */}
      <section className="px-8 py-20 max-w-5xl mx-auto w-full">
        <div className="reveal-item opacity-0">
          <h2 className="text-xs text-muted-foreground mb-8">
            Rem&apos;s model backbones
          </h2>
          <div className="flex items-baseline gap-8 text-lg font-medium">
            <span className="text-rem">Opus 4.6</span>
            <span className="text-rem/20">&middot;</span>
            <span className="text-rem">GLM-4.7V</span>
            <span className="text-rem/20">&middot;</span>
            <span className="text-rem">Nemotron</span>
          </div>
          <p className="text-sm text-muted-foreground mt-6 leading-relaxed max-w-lg">
            Each model brings different strengths. Opus excels at deep reasoning.
            GLM-4.7V adds vision for screenshot-based testing. Nemotron is
            RL-optimized for CTF-style challenges. Deploy all three, compare
            findings.
          </p>
        </div>

        <div className="reveal-item opacity-0 mt-14">
          <SignInButton mode="modal">
            <button className="text-sm bg-rem text-white px-8 py-3 hover:brightness-110 transition-all duration-150 active:translate-y-px">
              start scanning
            </button>
          </SignInButton>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────── */}
      <footer className="px-8 h-14 flex items-center border-t border-border">
        <span className="text-xs text-muted-foreground">return from zero</span>
      </footer>
    </div>
  );
}
