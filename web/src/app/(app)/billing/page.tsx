"use client";

import { useCustomer, CheckoutDialog } from "autumn-js/react";
import { RemLoader } from "@/components/rem-spinner";

const BILLING_URL = typeof window !== "undefined" ? `${window.location.origin}/billing` : "/billing";

export default function BillingPage() {
  const { customer, checkout, openBillingPortal, isLoading } = useCustomer();

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-12">
        <RemLoader />
      </div>
    );
  }

  const products = Array.isArray(customer?.products) ? customer.products : [];
  const hasSubscription = products.some(
    (p: any) => p.status === "active"
  );

  const scanFeature = (customer?.features as any)?.scan;
  const gateFeature = (customer?.features as any)?.gate_scan;

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-base font-semibold mb-8">billing</h1>

      {/* Subscription */}
      <section className="mb-12">
        <p className="text-xs text-muted-foreground mb-4">PLAN</p>
        {hasSubscription ? (
          <div className="border border-rem/30 bg-rem/5 p-4">
            <p className="text-sm font-medium">Pay-as-you-go</p>
            <div className="text-xs text-muted-foreground mt-3 space-y-1">
              <p>$25 / deep scan{scanFeature?.usage > 0 ? ` \u00b7 ${scanFeature.usage} used this period` : ""}</p>
              <p>$0.10 / gate scan{gateFeature?.usage > 0 ? ` \u00b7 ${gateFeature.usage} used this period` : ""}</p>
            </div>
          </div>
        ) : (
          <div className="border border-border p-4">
            <p className="text-sm text-muted-foreground mb-3">
              No active plan. Set up billing to start scanning.
            </p>
            <button
              onClick={() =>
                checkout({
                  productId: "pay-as-you-go",
                  successUrl: BILLING_URL,
                  dialog: CheckoutDialog,
                })
              }
              className="text-sm border border-rem/30 text-rem px-3 py-1 hover:bg-rem/5 transition-colors duration-100"
            >
              set up billing
            </button>
          </div>
        )}
      </section>

      {/* Scan packs */}
      {hasSubscription && (
        <section className="mb-12">
          <p className="text-xs text-muted-foreground mb-4">SCAN PACKS</p>
          {scanFeature?.balance > 0 && (
            <p className="text-sm mb-4">
              {scanFeature.balance} prepaid {scanFeature.balance === 1 ? "scan" : "scans"} remaining
            </p>
          )}
          <p className="text-xs text-muted-foreground mb-4">
            Prepaid bundles at a discount. Draws from packs first,
            then pay-as-you-go.
          </p>
          <div className="flex gap-3">
            <button
              onClick={() =>
                checkout({
                  productId: "standard-pack",
                  successUrl: BILLING_URL,
                  dialog: CheckoutDialog,
                })
              }
              className="text-sm border border-border px-3 py-2 hover:border-rem/30 transition-colors duration-100 flex-1"
            >
              <span className="block font-medium">10 scans — $212.50</span>
              <span className="block text-xs text-muted-foreground mt-1">
                $21.25/scan (15% off)
              </span>
            </button>
            <button
              onClick={() =>
                checkout({
                  productId: "bulk-pack",
                  successUrl: BILLING_URL,
                  dialog: CheckoutDialog,
                })
              }
              className="text-sm border border-border px-3 py-2 hover:border-rem/30 transition-colors duration-100 flex-1"
            >
              <span className="block font-medium">25 scans — $468.75</span>
              <span className="block text-xs text-muted-foreground mt-1">
                $18.75/scan (25% off)
              </span>
            </button>
          </div>
        </section>
      )}

      {/* Manage */}
      {hasSubscription && (
        <section>
          <p className="text-xs text-muted-foreground mb-4">MANAGE</p>
          <button
            onClick={() => openBillingPortal()}
            className="text-sm text-rem hover:underline"
          >
            payment methods, invoices & subscription
          </button>
        </section>
      )}
    </div>
  );
}
