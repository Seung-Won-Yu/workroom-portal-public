import type { ReactNode } from "react";

function normalizeAgentMarkdown(text: string) {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/\$\\rightarrow\$/g, "→")
    .replace(/\\rightarrow/g, "→")
    .trim();
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\))/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    if (match[2]) {
      nodes.push(<strong key={`b-${match.index}`}>{match[2]}</strong>);
    } else if (match[3]) {
      nodes.push(<code key={`c-${match.index}`}>{match[3]}</code>);
    } else if (match[4] && match[5]) {
      nodes.push(
        <a key={`a-${match.index}`} href={match[5]} target="_blank" rel="noreferrer">
          {match[4]}
        </a>,
      );
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export function MarkdownMessage({ text }: { text: string }) {
  const lines = normalizeAgentMarkdown(text).split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  let orderedList: string[] = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    const value = paragraph.join("\n").trim();
    if (value) blocks.push(<p key={`p-${blocks.length}`}>{renderInlineMarkdown(value)}</p>);
    paragraph = [];
  }

  function flushList() {
    if (list.length) {
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {list.map((item, index) => <li key={`${index}-${item}`}>{renderInlineMarkdown(item)}</li>)}
        </ul>,
      );
      list = [];
    }
    if (orderedList.length) {
      blocks.push(
        <ol key={`ol-${blocks.length}`}>
          {orderedList.map((item, index) => <li key={`${index}-${item}`}>{renderInlineMarkdown(item)}</li>)}
        </ol>,
      );
      orderedList = [];
    }
  }

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push(<h4 key={`h-${blocks.length}`}>{renderInlineMarkdown(heading[2])}</h4>);
      return;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      orderedList = [];
      list.push(bullet[1]);
      return;
    }
    const numbered = line.match(/^\d+\.\s+(.+)$/);
    if (numbered) {
      flushParagraph();
      list = [];
      orderedList.push(numbered[1]);
      return;
    }
    flushList();
    paragraph.push(line);
  });
  flushParagraph();
  flushList();

  return <div className="message-markdown">{blocks.length ? blocks : <p>{text}</p>}</div>;
}
