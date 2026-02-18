"use client";

import { useCustomer, CheckoutDialog } from "autumn-js/react";

const BILLING_URL = typeof window !== "undefined" ? `${window.location.origin}/billing` : "/billing";

export default function BillingPage() {
  const { customer, checkout, openBillingPortal, isLoading } = useCustomer({
    expand: ["features"],
  });

  // Debug: remove once billing is confirmed working
  if (customer) console.log("[billing] customer:", JSON.stringify(customer, null, 2));

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-12">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  const products = Array.isArray(customer?.products) ? customer.products : [];
  const hasSubscription = products.some(
    (p: any) => p.status === "active"
  );

  const features = Array.isArray(customer?.features) ? customer.features : [];
  const scanFeature = features.find(
    (f: any) => f.feature_id === "scan"
  );
  const gateFeature = features.find(
    (f: any) => f.feature_id === "gate_scan"
  );

  return (
    <div className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-base font-semibold mb-8">billing</h1>

      {/* Current status */}
      <section className="mb-12">
        <p className="text-xs text-muted-foreground mb-4">STATUS</p>
        {hasSubscription ? (
          <div className="border border-rem/30 bg-rem/5 p-4">
            <p className="text-sm">
              Active subscription
            </p>
            <div className="text-xs text-muted-foreground mt-2 space-y-1">
              {scanFeature && (
                <>
                  <p>Deep scans: $25/scan</p>
                  {scanFeature.balance > 0 && (
                    <p>{scanFeature.balance} prepaid scans remaining</p>
                  )}
                  {scanFeature.usage > 0 && (
                    <p>{scanFeature.usage} scans used this period</p>
                  )}
                </>
              )}
              {gateFeature && (
                <>
                  <p>Gate scans: $0.10/scan</p>
                  {gateFeature.usage > 0 && (
                    <p>{gateFeature.usage} gate scans this period</p>
                  )}
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="border border-border p-4">
            <p className="text-sm text-muted-foreground mb-3">
              No active subscription. Set up billing to start scanning.
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
          <p className="text-sm text-muted-foreground mb-4">
            Prepaid scan bundles at a discount. Scans draw from packs first
            before pay-as-you-go billing.
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
              <span className="block font-medium">10 scans</span>
              <span className="block text-xs text-muted-foreground mt-1">
                15% off
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
              <span className="block font-medium">25 scans</span>
              <span className="block text-xs text-muted-foreground mt-1">
                25% off
              </span>
            </button>
          </div>
        </section>
      )}

      {/* Manage */}
      <section>
        <p className="text-xs text-muted-foreground mb-4">MANAGE</p>
        <p className="text-sm text-muted-foreground">
          Manage payment methods, invoices, and subscription via Stripe.
        </p>
        <button
          onClick={() => openBillingPortal()}
          className="text-sm text-rem hover:underline mt-2"
        >
          open billing portal
        </button>
      </section>
    </div>
  );
}
