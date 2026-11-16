import { forwardRef } from "react";

interface Props {
  text: string;
  /** 1-based index of the match shown; 0 when none is shown yet. */
  index: number;
  total: number;
  onChange: (text: string) => void;
  onStep: (direction: 1 | -1) => void;
  onLeave: () => void;
}

/** The toolbar search box (heddle/search_bar.py): finds text in cards' titles, descriptions,
 *  notes and strands; Enter and Shift+Enter (or F3) step through the matches. */
export const SearchBar = forwardRef<HTMLInputElement, Props>(function SearchBar({ text, index, total, onChange, onStep, onLeave }, ref) {
  const count = !text.trim() ? "" : total === 0 ? "No matches" : index ? `${index} of ${total}` : `${total} found`;
  return (
    <span className="search" role="search">
      <input ref={ref} type="search" value={text} placeholder="Search cards (Ctrl+F)" aria-label="Search cards"
             onChange={(e) => onChange(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "Enter") {
                 e.preventDefault();
                 onStep(e.shiftKey ? -1 : 1);
               } else if (e.key === "Escape") {
                 e.preventDefault();
                 onChange("");
                 onLeave();
               }
             }} />
      <span className="search-count muted" aria-live="polite">{count}</span>
      <button type="button" className="icon" disabled={!total} onClick={() => onStep(-1)} title="Previous match (Shift+Enter, Shift+F3)" aria-label="Previous match">▲</button>
      <button type="button" className="icon" disabled={!total} onClick={() => onStep(1)} title="Next match (Enter, F3)" aria-label="Next match">▼</button>
    </span>
  );
});
