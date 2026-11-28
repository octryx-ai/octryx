// Latest wins: a late "New chat" answer reset the selected thread after a send, so superseded answers are dropped.

export type StateLoadSequence = {
  latest: number;
};

export function createStateLoadSequence(): StateLoadSequence {
  return { latest: 0 };
}

export function beginStateLoad(sequence: StateLoadSequence): number {
  sequence.latest += 1;
  return sequence.latest;
}

export function supersedeStateLoads(sequence: StateLoadSequence) {
  sequence.latest += 1;
}

export function isLatestStateLoad(sequence: StateLoadSequence, ticket: number): boolean {
  return ticket === sequence.latest;
}
