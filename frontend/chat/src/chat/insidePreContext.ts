import { createContext } from "react";

// react-markdown 9 does not pass `inline`; code is a block only inside <pre>.
export const InsidePreContext = createContext(false);
