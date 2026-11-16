import { FORMAT_VERSION } from "../core/model.ts";

/** Placeholder page for W0: proves the build and the GitHub Pages deploy work end to end. */
export function App() {
  return (
    <main className="placeholder">
      <img src={`${import.meta.env.BASE_URL}icon.svg`} alt="" width={64} height={64} />
      <h1>Heddle</h1>
      <p>Map branching and converging story paths: cards on a canvas joined by arrows.</p>
      <p>
        The browser version is being built. Until it's ready, the desktop app is on{" "}
        <a href="https://github.com/josh-logue/Heddle">GitHub</a>.
      </p>
      <p className="small">Board format {FORMAT_VERSION}</p>
    </main>
  );
}
