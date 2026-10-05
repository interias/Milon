import Link from "next/link";
import { PageTitle } from "@/components/ui";

export default function RunNotFound() {
  return <>
    <PageTitle title="Lauf nicht gefunden" sub="Diese Laufadresse ist ungültig." />
    <Link href="/laufen#strecken" scroll={false} className="text-sm font-semibold text-accent">← Zur Laufübersicht</Link>
  </>;
}
