import type { ThreadBlock } from "@ai4s/shared";

/**
 * One exchange: what the user asked, the work that followed, and the answer.
 *
 * The work is what folds away once the turn is done, leaving the ask and the
 * result — the shape Codex has, with an hour of process behind one line.
 */
export type Turn = {
  /** The user's message. Empty for a transcript that opens mid-conversation. */
  lead: ThreadBlock[];
  /** In order. A `foldable` run is the model working; anything else is a notice
   *  that has to stay on screen, and it breaks the run around it. */
  segments: TurnSegment[];
  /** The final answer, and anything the app shows after it. Never folded. */
  answer: ThreadBlock[];
};

export type TurnSegment = { foldable: boolean; blocks: ThreadBlock[] };

/**
 * The mechanical part of the model's work: commands and step summaries.
 *
 * Everything else stays on screen once the turn is done. That includes the
 * model's own mid-turn narration (stage updates, hypotheses, interim tables
 * printed between tool calls) and its reasoning — a long autonomous run is only
 * trustworthy if the reader can follow how it got to the answer. It also
 * includes the APP speaking — a reviewer's findings, a status line, a
 * compaction notice — where the next message often answers it ("the sub-agent
 * caught the swap"), so hiding it would leave the answer referring to
 * something the reader cannot see.
 */
const FOLDABLE = new Set(["tool-call", "step-summary"]);

/**
 * Drop reasoning blocks that carry no text.
 *
 * Non-empty thinking is kept and rendered as a dimmed, collapsible block,
 * visibly distinct from what the model SAID. An empty one (a reasoning part
 * opened and never filled) would draw nothing, so it is dropped here rather
 * than rendered as nothing — it cannot leave an empty segment behind.
 */
export function dropReasoning(blocks: ThreadBlock[]): ThreadBlock[] {
  const isEmpty = (b: ThreadBlock) => b.kind === "reasoning" && b.text.trim().length === 0;
  return blocks.some(isEmpty) ? blocks.filter((b) => !isEmpty(b)) : blocks;
}

/** Blocks that carry nothing of their own and must not, alone, make a fold. */
const isInvisible = (b: ThreadBlock): boolean => b.kind === "running-jobs";

/**
 * Split a thread into turns, each turn into the work and the answer, and the
 * work into foldable runs separated by whatever must stay visible.
 *
 * The answer is the LAST agent message of the turn: a model that narrates as it
 * goes writes several, and only the last is the result — the earlier ones are
 * progress narration, which sits in the work but stays visible (not FOLDABLE).
 *
 * A turn with no agent message yet is still running, so it has no answer and
 * nothing folds: the fold exists to hide work already finished. That is also why
 * no "is it running" flag has to be threaded down from the session — an
 * unanswered turn IS the running one.
 *
 * Pure — exported for tests.
 */
export function splitTurns(blocks: ThreadBlock[]): Turn[] {
  const turns: Turn[] = [];
  let current: ThreadBlock[] = [];
  const flush = () => {
    if (current.length === 0) return;
    const [lead, rest] =
      current[0]?.kind === "user" ? [[current[0]], current.slice(1)] : [[], current];
    // Searched over the REST, so a user message is never mistaken for an answer
    // and a turn that is only a question folds nothing. Stop if model work
    // (a tool call, reasoning, or step summary) appears after the last agent
    // message: that message is mid-turn narration (e.g. a stage update), and
    // the turn is still running.
    let answerAt = -1;
    for (let i = rest.length - 1; i >= 0; i--) {
      if (rest[i].kind === "agent") {
        answerAt = i;
        break;
      }
      if (
        rest[i].kind === "tool-call" ||
        rest[i].kind === "reasoning" ||
        rest[i].kind === "step-summary"
      ) {
        break;
      }
    }
    const work = answerAt === -1 ? rest : rest.slice(0, answerAt);
    turns.push({
      lead,
      segments: segmentsOf(work),
      answer: answerAt === -1 ? [] : rest.slice(answerAt),
    });
    current = [];
  };
  for (const b of blocks) {
    if (b.kind === "user") flush();
    current.push(b);
  }
  flush();
  return turns;
}

function segmentsOf(work: ThreadBlock[]): TurnSegment[] {
  const segments: TurnSegment[] = [];
  for (const b of work) {
    const foldable = FOLDABLE.has(b.kind);
    const tail = segments[segments.length - 1];
    if (tail && tail.foldable === foldable) tail.blocks.push(b);
    else segments.push({ foldable, blocks: [b] });
  }
  return segments;
}

/** Whether this turn's work is finished, and so may fold. */
export function isTurnDone(turn: Turn): boolean {
  return (
    turn.answer.length > 0 &&
    turn.segments.some((s) => s.foldable && s.blocks.some((b) => !isInvisible(b)))
  );
}

/**
 * How long a run of blocks took, in ms, or null when they do not say.
 *
 * Read off whatever each block stamps — tool calls carry `startedAt`/`endedAt`,
 * assistant messages `created`/`completed` — rather than from a turn-level
 * clock, because there is not one. A transcript loaded from history carries the
 * same stamps as a live run, so a reopened session shows the figure it showed
 * while it ran.
 */
export function spanMs(blocks: ThreadBlock[]): number | null {
  let first = Infinity;
  let last = -Infinity;
  for (const b of blocks) {
    const start = b.kind === "tool-call" ? b.startedAt : b.kind === "agent" ? b.created : undefined;
    const end = b.kind === "tool-call" ? b.endedAt : b.kind === "agent" ? b.completed : undefined;
    if (typeof start === "number") {
      first = Math.min(first, start);
      // A start with no end still bounds the span; a block that never stamped
      // its end would otherwise make a long run read as instantaneous.
      last = Math.max(last, start);
    }
    if (typeof end === "number") last = Math.max(last, end);
  }
  if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return null;
  return last - first;
}
