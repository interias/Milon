// Rendert die Markdown-Antworten des Coaches (Überschriften, Listen, Tabellen, Code).
import { marked } from "marked";

marked.setOptions({ gfm: true, breaks: true });

export function Markdown({ children }: { children: string }) {
  const html = marked.parse(children || "", { async: false }) as string;
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
