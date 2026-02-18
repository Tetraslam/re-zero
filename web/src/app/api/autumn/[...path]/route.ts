import { autumnHandler } from "autumn-js/next";
import { auth } from "@clerk/nextjs/server";

const handler = autumnHandler({
  identify: async () => {
    const { userId } = await auth();
    if (!userId) return null;
    return { customerId: userId };
  },
});

export const { GET, POST } = handler;
