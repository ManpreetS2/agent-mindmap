# Credits and third-party licenses (MINDMAP web)

The MINDMAP web app (`web/`) uses the following open-source components and patterns.
Upstream license texts remain in dependency packages under `web/node_modules/`.

| Source | Use in MINDMAP | License |
|--------|----------------|---------|
| [React](https://react.dev/) | UI runtime | MIT |
| [Vite](https://vitejs.dev/) | Bundler / dev server | MIT |
| [@xyflow/react](https://reactflow.dev/) (React Flow) | Agent graph canvas | MIT |
| [Tailwind CSS](https://tailwindcss.com/) | Utility styling | MIT |
| [tailwindcss-animate](https://github.com/jamiebuilds/tailwindcss-animate) | Tailwind animation utilities | MIT |
| [shadcn/ui](https://ui.shadcn.com/) | `Button` primitive pattern (`web/src/components/ui/button.tsx`) | MIT |
| [Radix UI](https://www.radix-ui.com/) (`@radix-ui/react-slot`) | shadcn Slot primitive | MIT |
| [class-variance-authority](https://cva.style/) | Button variants | Apache-2.0 |
| [clsx](https://github.com/lukeed/clsx) / [tailwind-merge](https://github.com/dcastil/tailwind-merge) | `cn()` helper | MIT |
| [Magic UI](https://magicui.design/) | Adapted `BorderBeam`, `AnimatedGridPattern`, `NumberTicker` (`web/src/components/magic/`) | MIT |
| [Vitest](https://vitest.dev/) / [Testing Library](https://testing-library.com/) / [axe-core](https://github.com/dequelabs/axe-core) | Tests & a11y checks | MIT |

**Not used in this phase:** Framer Motion / `motion`, Aceternity UI (no components copied; Aceternity Pro is separate from MIT snippets).

**Runtime:** No CDN fonts or external network assets; system / bundled CSS only.

Copied/adapted files retain MIT notices in file headers where applicable.
