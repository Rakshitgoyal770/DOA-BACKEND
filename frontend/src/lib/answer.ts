/**
 * Parse the analyst's answer text into a structure React can render safely (no
 * dangerouslySetInnerHTML).
 *
 * The backend's writer is instructed (features/chat/prompt.py) to mark where each fact
 * comes from:
 *     [Source 1]  or  [Source 1, Source 2]   a forum / proposal passage returned in `sources`
 *     [Facts]                                a database lookup returned in `lookups`
 *     [Background]                           general knowledge, NOT from our data
 * and models commonly add light markdown (**bold**, "- " bullets, "1." lists).
 * We turn those markers into chips the UI can link to the evidence list.
 */
export type Inline =
  | { type: 'text'; text: string }
  | { type: 'bold'; text: string }
  | { type: 'cite'; numbers: number[] }
  | { type: 'facts' }
  | { type: 'background' };

export type Block =
  | { type: 'p'; content: Inline[] }
  | { type: 'ul' | 'ol'; items: Inline[][] };

// Brackets are [ ] normally, but some providers (seen from Groq in practice) emit full-width 【 】 instead.
const OPEN = '[\\[【]';
const CLOSE = '[\\]】]';
const INLINE_RE = new RegExp(
  `\\*\\*([^*]+)\\*\\*|${OPEN}((?:Sources?\\s*)?\\d+(?:\\s*,\\s*(?:Sources?\\s*)?\\d+)*)${CLOSE}|${OPEN}(Facts)${CLOSE}|${OPEN}(Background)${CLOSE}`,
  'gi',
);

export function parseInline(line: string): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  for (const m of line.matchAll(INLINE_RE)) {
    const index = m.index ?? 0;
    // "[3]" alone is too ambiguous to treat as a citation; require the word "Source".
    if (m[2] !== undefined && !/source/i.test(m[2])) continue;
    if (index > last) out.push({ type: 'text', text: line.slice(last, index) });
    if (m[1] !== undefined) out.push({ type: 'bold', text: m[1] });
    else if (m[2] !== undefined) out.push({ type: 'cite', numbers: [...m[2].matchAll(/\d+/g)].map((n) => Number(n[0])) });
    else if (m[3] !== undefined) out.push({ type: 'facts' });
    else out.push({ type: 'background' });
    last = index + m[0].length;
  }
  if (last < line.length) out.push({ type: 'text', text: line.slice(last) });
  return out;
}

export function parseAnswer(answer: string): Block[] {
  const blocks: Block[] = [];
  const lines = answer.replace(/\r\n/g, '\n').split('\n');
  let paragraph: string[] = [];
  let list: { kind: 'ul' | 'ol'; items: Inline[][] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: 'p', content: parseInline(paragraph.join(' ')) });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push({ type: list.kind, items: list.items });
    list = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const kind = bullet ? 'ul' : 'ol';
      if (list && list.kind !== kind) flushList();
      if (!list) list = { kind, items: [] };
      list.items.push(parseInline((bullet ?? numbered)![1]));
    } else if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: 'p', content: [{ type: 'bold', text: heading[1] }] });
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
