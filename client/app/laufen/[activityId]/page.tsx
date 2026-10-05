import { notFound } from "next/navigation";
import { RunActivityDetail } from "@/components/RunActivityDetail";

export const metadata = { title: "Laufdetails · Milon" };

export default async function RunDetailPage({ params }: { params: Promise<{ activityId: string }> }) {
  const { activityId } = await params;
  if (!/^[0-9]{1,30}$/.test(activityId)) notFound();
  return <RunActivityDetail key={activityId} activityId={activityId} />;
}
