// Latest wins for chat state.
//
// "New chat" starts a `loadState('?new=1')`; when its answer arrived after the send acknowledgement,
// it reset the selected thread and the next message opened yet another thread. Every load takes a
// ticket; applying any newer state (another load, a send acknowledgement) supersedes older tickets,
// and a superseded answer is dropped.

export type StateLoadSequence = {
  latest: number;
};

export function createStateLoadSequence(): StateLoadSequence {
  return { latest: 0 };
}

/** A ticket for a load that is about to start; it supersedes every earlier one. */
export function beginStateLoad(sequence: StateLoadSequence): number {
  sequence.latest += 1;
  return sequence.latest;
}

/** A state applied outside a load (send acknowledgement, action answer) supersedes running loads. */
export function supersedeStateLoads(sequence: StateLoadSequence) {
  sequence.latest += 1;
}

export function isLatestStateLoad(sequence: StateLoadSequence, ticket: number): boolean {
  return ticket === sequence.latest;
}
