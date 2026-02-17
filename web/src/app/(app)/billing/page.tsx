"use client";

import { useCustomer, CheckoutDialog } from "autumn-js/react";

export default function BillingPage() {
  const { customer, checkout, isLoading } = useCustomer();

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-12">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  const hasSubscription = (customer?.products as any[])?.some(
    (p: any) => p.status === "active"
  );

  const features = customer?.features as any[] | undefined;
  const scanFeature = features?.find(
    (f: any) => f.feature_id === "scan"
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
            {scanFeature && (
              <p className="text-xs text-muted-foreground mt-2">
                {scanFeature.unlimited
                  ? "Unlimited scans (pay-as-you-go)"
                  : `${scanFeature.balance ?? 0} scans remaining`}
                {scanFeature.usage != null && (
                  <span className="ml-2">
                    ({scanFeature.usage} used this period)
                  </span>
                )}
              </p>
            )}
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
          onClick={() => {
            // billingPortal opens Stripe's portal
            if ((window as any).__autumn_billing_portal) {
              (window as any).__autumn_billing_portal();
            }
          }}
          className="text-sm text-rem hover:underline mt-2"
        >
          open billing portal
        </button>
      </section>
    </div>
  );
}
