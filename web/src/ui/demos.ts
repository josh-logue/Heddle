// The demo boards from examples/, bundled with the site and loaded when opened.

export interface Demo {
  id: string;
  name: string;
  blurb: string;
  load: () => Promise<string>;
}

export const DEMOS: readonly Demo[] = [
  {
    id: "lantern-tide",
    name: "Lantern Tide",
    blurb: "A branching story: routes that split and meet again, a loop, several endings.",
    load: () => import("../../../examples/lantern-tide.json?raw").then((m) => m.default),
  },
  {
    id: "hollybank-garden",
    name: "Hollybank Garden",
    blurb: "A board for sorting: plants in nested groups, no arrows.",
    load: () => import("../../../examples/hollybank-garden.json?raw").then((m) => m.default),
  },
];

export const demoById = (id: string | null) => DEMOS.find((d) => d.id === id) ?? null;
