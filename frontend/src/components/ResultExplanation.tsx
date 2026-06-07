export type ResultExplanationProps = {
  markdown: string;
};

/** Very small Markdown renderer for headings, lists and paragraphs.
 *  We intentionally keep it dependency-free so we don't need to ship a
 *  full markdown parser for the small summaries the backend emits. */
export function ResultExplanation({ markdown }: ResultExplanationProps): JSX.Element | null {
  if (!markdown || !markdown.trim()) {
    return null;
  }
  const blocks = markdown
    .replace(/\r\n/g, "\n")
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  return (
    <section className="result-explanation" data-testid="result-explanation">
      <h4 className="result-explanation__title">AI 解释</h4>
      <div className="result-explanation__body">
        {blocks.map((block, idx) => renderBlock(block, idx))}
      </div>
    </section>
  );
}

function renderBlock(block: string, idx: number): JSX.Element {
  // Headings
  const headingMatch = /^(#{1,6})\s+(.*)$/.exec(block);
  if (headingMatch) {
    const level = headingMatch[1].length;
    const text = headingMatch[2];
    const Tag = (`h${Math.min(6, Math.max(2, level + 1))}`) as keyof JSX.IntrinsicElements;
    return <Tag key={idx}>{text}</Tag>;
  }
  // Bullet list
  if (block.split("\n").every((line) => /^[-*•]\s+/.test(line.trim()))) {
    const items = block.split("\n").map((line) => line.replace(/^[-*•]\s+/, ""));
    return (
      <ul key={idx} className="result-explanation__list">
        {items.map((item, j) => (
          <li key={j}>{item}</li>
        ))}
      </ul>
    );
  }
  // Paragraph
  return (
    <p key={idx} className="result-explanation__paragraph">
      {block}
    </p>
  );
}
