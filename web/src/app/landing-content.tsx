"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { SignInButton } from "@clerk/nextjs";
import dynamic from "next/dynamic";

const Dithering = dynamic(
  () => import("@paper-design/shaders-react").then((m) => m.Dithering),
  { ssr: false }
);

/* ── Terminal scan data ──────────────────────────────── */
const SCAN_LINES: { type: string; text: string }[] = [
  { type: "cmd", text: "$ rem deploy --target github.com/acme/payments-api" },
  { type: "sys", text: "  indexing 1,247 files \u00b7 building dependency graph" },
  { type: "blank", text: "" },
  { type: "reason", text: "\u2502 Payments API \u2014 starting with auth middleware and transaction endpoints." },
  { type: "tool", text: "\u2192 read_file  src/middleware/auth.ts" },
  { type: "tool", text: "\u2192 read_file  src/routes/transactions.ts" },
  { type: "reason", text: "\u2502 JWT secret from env without validation. Missing var = silent auth bypass." },
  { type: "finding-critical", text: "\u25a0 VN-001  CRITICAL  Auth bypass via missing JWT secret" },
  { type: "blank", text: "" },
  { type: "tool", text: "\u2192 search_code  \"query(\" \"raw(\" \"execute(\"" },
  { type: "reason", text: "\u2502 Raw SQL in transaction search. User input flows into WHERE clause." },
  { type: "finding-high", text: "\u25a0 VN-002  HIGH      SQL injection in /api/transactions" },
  { type: "blank", text: "" },
  { type: "tool", text: "\u2192 read_file  src/utils/crypto.ts" },
  { type: "reason", text: "\u2502 AES-ECB mode for card numbers. Same card \u2192 same ciphertext." },
  { type: "finding-critical", text: "\u25a0 VN-003  CRITICAL  Deterministic encryption (AES-ECB)" },
  { type: "blank", text: "" },
  { type: "sys", text: "  complete \u2014 3 findings \u00b7 2 critical \u00b7 1 high" },
];

/* ── Mode visuals ────────────────────────────────────── */

function OssVisual() {
  const lines = [
    { n: 1, code: "import jwt from 'jsonwebtoken';", hl: "" },
    { n: 2, code: "", hl: "" },
    { n: 3, code: 'const SECRET = "sk-prod-a8f3e2d1";', hl: "critical" },
    { n: 4, code: "", hl: "" },
    { n: 5, code: "app.get('/users/:id', (req, res) => {", hl: "" },
    { n: 6, code: "  db.query(`SELECT * FROM users", hl: "high" },
    { n: 7, code: "    WHERE id = ${req.params.id}`)", hl: "high" },
    { n: 8, code: "});", hl: "" },
  ];
  return (
    <div className="font-mono text-[10px] sm:text-[11px] leading-[2] border border-[#222645] p-3 sm:p-4 overflow-x-auto">
      {lines.map((l) => (
        <div
          key={l.n}
          className={
            l.hl === "critical"
              ? "text-[#dc4242]/80 bg-[#dc4242]/8 -mx-3 sm:-mx-4 px-3 sm:px-4"
              : l.hl === "high"
                ? "text-[#e8a84f]/80 bg-[#e8a84f]/8 -mx-3 sm:-mx-4 px-3 sm:px-4"
                : "text-[#cfd2e3]/40"
          }
        >
          <span className="text-[#cfd2e3]/20 inline-block w-4 text-right mr-4 select-none">
            {l.n}
          </span>
          {l.code}
        </div>
      ))}
    </div>
  );
}

function WebVisual() {
  return (
    <svg viewBox="0 0 260 180" fill="none" className="w-full max-w-[280px] mx-auto">
      <rect x="0.5" y="0.5" width="259" height="179" stroke="#6b82ff" strokeWidth="1" opacity="0.35" />
      <line x1="0" y1="24" x2="260" y2="24" stroke="#6b82ff" strokeWidth="0.5" opacity="0.3" />
      <rect x="6" y="4" width="70" height="16" stroke="#6b82ff" strokeWidth="0.5" opacity="0.2" />
      <rect x="6" y="28" width="248" height="14" stroke="#6b82ff" strokeWidth="0.5" opacity="0.2" />
      <text x="12" y="38" fill="#6b82ff" fontSize="7" fontFamily="monospace" opacity="0.4">
        https://target.com/login
      </text>
      <rect x="12" y="52" width="90" height="7" fill="#6b82ff" opacity="0.12" />
      <rect x="12" y="64" width="236" height="4" fill="#6b82ff" opacity="0.08" />
      <rect x="12" y="72" width="180" height="4" fill="#6b82ff" opacity="0.08" />
      <rect x="12" y="88" width="160" height="76" stroke="#dc4242" strokeWidth="1.5" opacity="0.5">
        <animate attributeName="opacity" values="0.35;0.6;0.35" dur="2s" repeatCount="indefinite" />
      </rect>
      <rect x="20" y="96" width="144" height="12" stroke="#6b82ff" strokeWidth="0.5" opacity="0.2" />
      <rect x="20" y="114" width="144" height="12" stroke="#6b82ff" strokeWidth="0.5" opacity="0.2" />
      <rect x="20" y="134" width="70" height="16" fill="#6b82ff" opacity="0.15" />
      <text x="180" y="105" fill="#dc4242" fontSize="6.5" fontFamily="monospace" opacity="0.6">
        {"<script>"}
      </text>
      <text x="180" y="120" fill="#e8a84f" fontSize="6.5" fontFamily="monospace" opacity="0.6">
        CSRF token
      </text>
      <text x="180" y="135" fill="#dc4242" fontSize="6.5" fontFamily="monospace" opacity="0.6">
        SSRF probe
      </text>
      <line x1="82" y1="110" x2="112" y2="110" stroke="#dc4242" strokeWidth="0.8" opacity="0.4" />
      <line x1="97" y1="95" x2="97" y2="125" stroke="#dc4242" strokeWidth="0.8" opacity="0.4" />
      <circle cx="97" cy="110" r="15" stroke="#dc4242" strokeWidth="0.8" opacity="0.3">
        <animate attributeName="r" values="12;18;12" dur="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.3;0.1;0.3" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

function DroneVisual() {
  return (
    <svg viewBox="0 0 200 200" fill="none" className="w-full max-w-[200px] sm:max-w-[240px] mx-auto">
      <line x1="34" y1="34" x2="84" y2="84" stroke="#6b82ff" strokeWidth="1.5" opacity="0.45" />
      <line x1="166" y1="34" x2="116" y2="84" stroke="#6b82ff" strokeWidth="1.5" opacity="0.45" />
      <line x1="34" y1="166" x2="84" y2="116" stroke="#6b82ff" strokeWidth="1.5" opacity="0.45" />
      <line x1="166" y1="166" x2="116" y2="116" stroke="#6b82ff" strokeWidth="1.5" opacity="0.45" />
      <rect x="82" y="82" width="36" height="36" stroke="#6b82ff" strokeWidth="1.5" fill="none" opacity="0.55" />
      <circle cx="34" cy="34" r="22" stroke="#6b82ff" strokeWidth="1" opacity="0.35" />
      <circle cx="166" cy="34" r="22" stroke="#6b82ff" strokeWidth="1" opacity="0.35" />
      <circle cx="34" cy="166" r="22" stroke="#6b82ff" strokeWidth="1" opacity="0.35" />
      <circle cx="166" cy="166" r="22" stroke="#6b82ff" strokeWidth="1" opacity="0.35" />
      <circle cx="34" cy="34" r="2.5" fill="#6b82ff" opacity="0.6" />
      <circle cx="166" cy="34" r="2.5" fill="#6b82ff" opacity="0.6" />
      <circle cx="34" cy="166" r="2.5" fill="#6b82ff" opacity="0.6" />
      <circle cx="166" cy="166" r="2.5" fill="#6b82ff" opacity="0.6" />
      <circle cx="100" cy="100" r="40" stroke="#6b82ff" strokeWidth="0.8" opacity="0">
        <animate attributeName="r" from="40" to="96" dur="3s" repeatCount="indefinite" />
        <animate attributeName="opacity" from="0.3" to="0" dur="3s" repeatCount="indefinite" />
      </circle>
      <circle cx="100" cy="100" r="40" stroke="#6b82ff" strokeWidth="0.8" opacity="0">
        <animate attributeName="r" from="40" to="96" dur="3s" begin="1s" repeatCount="indefinite" />
        <animate attributeName="opacity" from="0.3" to="0" dur="3s" begin="1s" repeatCount="indefinite" />
      </circle>
      <circle cx="100" cy="100" r="40" stroke="#6b82ff" strokeWidth="0.8" opacity="0">
        <animate attributeName="r" from="40" to="96" dur="3s" begin="2s" repeatCount="indefinite" />
        <animate attributeName="opacity" from="0.3" to="0" dur="3s" begin="2s" repeatCount="indefinite" />
      </circle>
      <text x="100" y="196" fill="#cfd2e3" fontSize="7" fontFamily="monospace" textAnchor="middle" opacity="0.3">
        MAVLink v2
      </text>
    </svg>
  );
}

function FpgaVisual() {
  return (
    <svg viewBox="0 0 400 130" fill="none" className="w-full" preserveAspectRatio="xMidYMid meet">
      <line x1="0" y1="30" x2="400" y2="30" stroke="#6b82ff" strokeWidth="0.3" opacity="0.15" />
      <line x1="0" y1="60" x2="400" y2="60" stroke="#6b82ff" strokeWidth="0.3" opacity="0.15" />
      <line x1="0" y1="90" x2="400" y2="90" stroke="#6b82ff" strokeWidth="0.3" opacity="0.15" />
      <polyline
        className="power-trace"
        style={{ strokeDasharray: 1200, strokeDashoffset: 1200 }}
        points="0,60 10,61 20,59 30,60 40,61 50,60 60,58 65,55 70,18 73,80 76,22 79,75 82,28 85,70 88,55 93,58 100,60 110,61 120,59 130,60 140,61 150,60 155,58 160,55 165,20 168,78 171,24 174,73 177,30 180,68 183,55 188,58 195,60 205,61 215,59 225,60 235,61 245,60 250,58 255,55 260,22 263,76 266,26 269,72 272,32 275,66 278,55 283,58 290,60 300,61 310,59 320,60 330,61 340,58 345,55 350,19 353,79 356,23 359,74 362,29 365,69 368,55 373,58 380,60 390,61 400,60"
        stroke="#6b82ff"
        strokeWidth="1.5"
        opacity="0.7"
      />
      <text className="key-anno" x="76" y="108" fill="#dc4242" fontSize="7" fontFamily="monospace" opacity="0">0x4F</text>
      <text className="key-anno" x="171" y="108" fill="#dc4242" fontSize="7" fontFamily="monospace" opacity="0">0x68</text>
      <text className="key-anno" x="266" y="108" fill="#dc4242" fontSize="7" fontFamily="monospace" opacity="0">0xE8</text>
      <text className="key-anno" x="359" y="108" fill="#dc4242" fontSize="7" fontFamily="monospace" opacity="0">0xA1</text>
      <line x1="0" y1="0" x2="0" y2="130" stroke="#6b82ff" strokeWidth="1" opacity="0.35">
        <animate attributeName="x1" from="0" to="400" dur="4s" repeatCount="indefinite" />
        <animate attributeName="x2" from="0" to="400" dur="4s" repeatCount="indefinite" />
      </line>
      <text x="0" y="126" fill="#cfd2e3" fontSize="6" fontFamily="monospace" opacity="0.25">power (mW)</text>
      <text x="375" y="126" fill="#cfd2e3" fontSize="6" fontFamily="monospace" opacity="0.25">time</text>
    </svg>
  );
}

/* ── Mode data ───────────────────────────────────────── */
const MODES = [
  {
    id: "oss",
    cmd: "oss",
    tagline: "every line, every path, every secret",
    desc: "Full source tree analysis. Rem traces data flows through your codebase \u2014 injection points, auth bypasses, hardcoded credentials, dangerous crypto. Every file she deems relevant gets read and analyzed.",
  },
  {
    id: "web",
    cmd: "web",
    tagline: "your browser, her weapon",
    desc: "Rem takes the wheel of a headless browser and attacks your web app like a human pentester. She navigates pages, fills forms, injects payloads, and discovers XSS, CSRF, SSRF, IDOR \u2014 the full OWASP top 10.",
  },
  {
    id: "hardware",
    cmd: "hardware",
    tagline: "intercept the signal, own the sky",
    desc: "Connect a drone, ESP32, or any device via gateway. Rem extracts firmware, fuzzes MAVLink and serial protocols, and probes for radio vulnerabilities. Full flight controller analysis from a sandboxed environment.",
  },
  {
    id: "fpga",
    cmd: "fpga",
    tagline: "your power trace betrays your key",
    desc: "Side-channel attacks on hardware crypto. Rem monitors power consumption during AES-256 operations, applies differential power analysis, and extracts the full encryption key byte by byte.",
  },
];

const MODE_VISUAL: Record<string, React.ReactNode> = {
  oss: <OssVisual />,
  web: <WebVisual />,
  hardware: <DroneVisual />,
  fpga: <FpgaVisual />,
};

/* ── Main component ──────────────────────────────────── */

export function LandingContent() {
  const root = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);
  const animated = useRef(new Set<string>());

  useEffect(() => {
    setMounted(true);
  }, []);

  const setupScrollAnimations = useCallback(
    async (rootEl: HTMLDivElement) => {
      const { animate, stagger } = await import("animejs");

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const id = (entry.target as HTMLElement).dataset.section;
            if (!id || animated.current.has(id)) return;
            animated.current.add(id);

            if (id === "terminal") {
              const lines = entry.target.querySelectorAll(".scan-line");
              animate(lines, {
                opacity: [0, 1],
                translateX: ["-0.5rem", "0rem"],
                delay: stagger(120, { start: 200 }),
                duration: 350,
                ease: "outQuart",
              });
              const cursor = entry.target.querySelector(".term-cursor");
              if (cursor) {
                animate(cursor, {
                  opacity: [0, 1],
                  delay: 120 * lines.length + 600,
                  duration: 1,
                });
              }
            }

            // Each mode panel animates individually
            if (id?.startsWith("mode-")) {
              animate(entry.target, {
                opacity: [0, 1],
                translateY: ["2rem", "0rem"],
                duration: 1000,
                ease: "outExpo",
              });

              // FPGA: draw the power trace
              if (id === "mode-fpga") {
                const trace = entry.target.querySelector(".power-trace");
                if (trace) {
                  animate(trace, {
                    strokeDashoffset: [1200, 0],
                    delay: 500,
                    duration: 2500,
                    ease: "outQuart",
                  });
                }
                animate(entry.target.querySelectorAll(".key-anno"), {
                  opacity: [0, 1],
                  translateY: [4, 0],
                  delay: stagger(200, { start: 2800 }),
                  duration: 600,
                  ease: "outQuart",
                });
              }
            }

            if (id === "closing") {
              animate(entry.target.querySelectorAll(".close-inner"), {
                opacity: [0, 1],
                translateY: ["1.5rem", "0rem"],
                duration: 1000,
                ease: "outExpo",
              });
            }

            observer.unobserve(entry.target);
          });
        },
        { threshold: 0.1 }
      );

      rootEl.querySelectorAll("[data-section]").forEach((el) => {
        if ((el as HTMLElement).dataset.section !== "hero") {
          observer.observe(el);
        }
      });

      return observer;
    },
    []
  );

  useEffect(() => {
    if (!mounted || !root.current) return;

    let observer: IntersectionObserver | null = null;

    (async () => {
      const { createTimeline } = await import("animejs");

      createTimeline({ defaults: { ease: "outExpo" } })
        .add(".hero-gif-wrap", {
          opacity: [0, 1],
          scale: [1.03, 1],
          duration: 1200,
        })
        .add(
          ".hero-title",
          { opacity: [0, 1], translateY: ["1rem", "0rem"], duration: 800 },
          "-=600"
        )
        .add(
          ".hero-tagline",
          { opacity: [0, 1], translateY: ["0.75rem", "0rem"], duration: 800 },
          "-=400"
        )
        .add(
          ".hero-cta",
          { opacity: [0, 1], translateY: ["0.5rem", "0rem"], duration: 700 },
          "-=400"
        );

      observer = await setupScrollAnimations(root.current!);
    })();

    return () => observer?.disconnect();
  }, [mounted, setupScrollAnimations]);

  return (
    <div ref={root} className="flex min-h-dvh flex-col overflow-x-hidden">
      {/* ═══ HERO ═══════════════════════════════════════ */}
      <section
        data-section="hero"
        className="relative min-h-dvh flex flex-col"
      >
        {mounted && (
          <div className="absolute inset-0 z-0 overflow-hidden">
            <Dithering
              colorBack="#f7f7fc"
              colorFront="#4f68e8"
              shape="simplex"
              type="4x4"
              size={2}
              speed={0.15}
              scale={0.8}
              style={{ width: "100%", height: "100%", opacity: 0.1 }}
            />
          </div>
        )}

        <header className="relative z-10 px-6 sm:px-8 h-11 flex items-center justify-between border-b border-border mt-[2px]">
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

        <div className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 sm:px-8 pb-16">
          <div className="hero-gif-wrap relative w-full max-w-[720px] aspect-[500/281] mb-10 sm:mb-12 opacity-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/rem-hero.gif"
              alt="Rem"
              className="w-full h-full object-cover"
            />
            {mounted && (
              <div
                className="absolute inset-0 pointer-events-none"
                style={{ mixBlendMode: "overlay", opacity: 0.2 }}
              >
                <Dithering
                  colorBack="#000000"
                  colorFront="#ffffff"
                  shape="simplex"
                  type="4x4"
                  size={3}
                  speed={0.2}
                  scale={1.0}
                  style={{ width: "100%", height: "100%" }}
                />
              </div>
            )}
            <div className="absolute inset-0 border border-border pointer-events-none" />
          </div>

          <h1 className="hero-title text-5xl sm:text-6xl md:text-7xl font-semibold tracking-tight text-center leading-none opacity-0">
            <span>re</span>
            <span className="text-destructive">:</span>
            <span>zero</span>
          </h1>

          <p className="hero-tagline text-base sm:text-lg text-muted-foreground mt-5 sm:mt-6 text-center max-w-md leading-relaxed opacity-0">
            deploy Rem to red team any attack surface.
          </p>

          <div className="hero-cta mt-8 sm:mt-10 flex flex-col items-center gap-3 opacity-0">
            <SignInButton mode="modal">
              <button className="text-sm bg-rem text-white px-8 py-3 hover:brightness-110 transition-all duration-150 active:translate-y-px">
                deploy Rem
              </button>
            </SignInButton>
            <span className="text-xs text-muted-foreground/50">
              autonomous security analysis in minutes
            </span>
          </div>
        </div>

        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
          <div className="w-px h-8 bg-border animate-pulse" />
        </div>
      </section>

      {/* ── Transition: light → dark ─────────────────── */}
      <div
        className="h-12 sm:h-20"
        style={{ background: "linear-gradient(to bottom, #f7f7fc, #0c0e1a)" }}
      />

      {/* ═══ DARK ZONE ═════════════════════════════════ */}
      <div className="relative bg-[#0c0e1a]">
        {mounted && (
          <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
            <Dithering
              colorBack="#0c0e1a"
              colorFront="#4f68e8"
              shape="simplex"
              type="4x4"
              size={2}
              speed={0.05}
              scale={0.5}
              style={{ width: "100%", height: "100%", opacity: 0.07 }}
            />
          </div>
        )}

        {/* ── Terminal ─────────────────────────────── */}
        <section
          data-section="terminal"
          className="relative z-10 max-w-4xl mx-auto px-6 sm:px-8 pt-16 sm:pt-24 pb-16"
        >
          <div className="flex items-center gap-2.5 mb-8 sm:mb-10">
            <div className="w-[7px] h-[7px] rounded-full bg-[#c53528]/60" />
            <div className="w-[7px] h-[7px] rounded-full bg-[#c5a028]/60" />
            <div className="w-[7px] h-[7px] rounded-full bg-[#28c55a]/60" />
            <span className="text-[11px] text-[#cfd2e3]/35 ml-3 font-mono">
              rem &mdash; live scan
            </span>
          </div>

          <div className="font-mono text-[12px] sm:text-[13px] leading-[1.9] overflow-x-auto">
            {SCAN_LINES.map((line, i) => (
              <div
                key={i}
                className={`scan-line opacity-0 whitespace-pre ${
                  line.type === "blank"
                    ? "h-3"
                    : line.type === "cmd"
                      ? "text-white"
                      : line.type === "sys"
                        ? "text-[#cfd2e3]/45"
                        : line.type === "reason"
                          ? "text-[#6b82ff]/80"
                          : line.type === "tool"
                            ? "text-[#cfd2e3]/40"
                            : line.type === "finding-critical"
                              ? "text-[#dc4242]"
                              : line.type === "finding-high"
                                ? "text-[#e8a84f]"
                                : "text-[#cfd2e3]/30"
                }`}
              >
                {line.text}
              </div>
            ))}
            <span className="term-cursor opacity-0 inline-block w-[7px] h-[14px] bg-[#6b82ff] animate-pulse mt-1" />
          </div>
        </section>

        {/* ── Attack modes ─────────────────────────── */}
        <section className="relative z-10 border-t border-[#222645] px-6 sm:px-8 pb-16 sm:pb-24 pt-16 sm:pt-20">
          <div className="max-w-6xl mx-auto">
            <span className="text-[11px] text-[#cfd2e3]/35 font-mono tracking-widest uppercase">
              Attack modes
            </span>

            <div className="mt-12 sm:mt-16 space-y-16 sm:space-y-28">
              {MODES.map((m, i) => (
                <div
                  key={m.id}
                  data-section={`mode-${m.id}`}
                  className={`mode-panel opacity-0 flex flex-col ${
                    i % 2 === 1 ? "lg:flex-row-reverse" : "lg:flex-row"
                  } gap-8 sm:gap-10 lg:gap-16 items-center`}
                >
                  <div className="w-full lg:w-2/5 shrink-0">
                    {MODE_VISUAL[m.id]}
                  </div>
                  <div className="w-full lg:w-3/5">
                    <h3 className="font-mono text-[13px] sm:text-[15px] text-white">
                      $ rem --mode{" "}
                      <span className="text-[#6b82ff]">{m.cmd}</span>
                    </h3>
                    <p className="text-[12px] sm:text-[13px] text-[#cfd2e3]/50 mt-2 italic">
                      {m.tagline}
                    </p>
                    <p className="text-[13px] text-[#cfd2e3]/60 mt-5 leading-relaxed max-w-md">
                      {m.desc}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      {/* ── Transition: dark → light ─────────────────── */}
      <div
        className="h-12 sm:h-20"
        style={{ background: "linear-gradient(to bottom, #0c0e1a, #f7f7fc)" }}
      />

      {/* ═══ CLOSING ═══════════════════════════════════ */}
      <section
        data-section="closing"
        className="relative overflow-hidden min-h-[70vh] flex flex-col"
      >
        {mounted && (
          <div className="absolute inset-0 z-0">
            <Dithering
              colorBack="#f7f7fc"
              colorFront="#4f68e8"
              shape="sphere"
              type="4x4"
              size={3}
              speed={0.1}
              scale={0.4}
              style={{ width: "100%", height: "100%", opacity: 0.06 }}
            />
          </div>
        )}

        <div className="close-inner relative z-10 flex-1 flex flex-col items-center justify-center gap-8 opacity-0">
          <span className="text-[11px] text-muted-foreground font-mono tracking-widest">
            OPUS 4.6 &middot; GLM-4.7V &middot; NEMOTRON
          </span>

          <h2 className="text-4xl sm:text-6xl font-semibold tracking-tight text-center">
            deploy <span className="text-rem">Rem</span>
          </h2>

          <SignInButton mode="modal">
            <button className="text-sm bg-rem text-white px-10 py-3.5 hover:brightness-110 transition-all duration-150 active:translate-y-px mt-2">
              start scanning
            </button>
          </SignInButton>

          <p className="text-sm text-muted-foreground/70 text-center max-w-xs leading-relaxed mt-4">
            Rem probes, fails, learns, returns.
            <br />
            Each scan is a life. Knowledge accumulates.
          </p>
        </div>

        <footer className="relative z-10 px-6 sm:px-8 h-14 flex items-center border-t border-border">
          <span className="text-xs text-muted-foreground">return from zero</span>
        </footer>
      </section>
    </div>
  );
}
