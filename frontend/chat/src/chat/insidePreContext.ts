// Whether markdown code renders inside a <pre> block: only there it is a code block, elsewhere inline code.

import { createContext } from "react";

// react-markdown 9 does not pass `inline` to the code component; code is a
// block only inside <pre>. Without this, inline code such as `/owners` would go
// through the block heuristics and become a reference card in the middle of a
// sentence.
export const InsidePreContext = createContext(false);
