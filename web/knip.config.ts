import type { KnipConfig } from "knip";

const config: KnipConfig = {
  project: ["src/**/*.{ts,tsx}"],
  ignore: ["src/components/ui/**"],  // shadcn generated, don't flag
  ignoreDependencies: [
    "tw-animate-css",       // tailwind plugin, referenced in CSS
  ],
};

export default config;
