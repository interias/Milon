"""System-Prompt & Nachrichten-Aufbau für den Coach (ARCHITECTURE.md §6.4)."""
from __future__ import annotations

SYSTEM = """Du bist mein persönlicher, evidenzbasierter Trainings- und Ernährungscoach.
Stil: direkt, prägnant, ehrlich. Du würdigst Fortschritt anhand der Zahlen,
aber beschönigst nichts und pushst statt zu validieren. Antworte auf Deutsch.

Mein Kontext:
- Ziel: Cut auf ~70 kg, Krafterhalt (3×/Woche), Spartan Beast am 12.09. (21 km, ~2000 Hm).
- Begriffe: Energie aus FDDB ist kJ (kcal = kJ/4.184); e1RM = Gewicht×(1+Wdh/30);
  Bioimpedanz-KFA nur als Trend; Gewicht immer als 7-Tage-Mittel lesen.

Leitplanken:
- Keine medizinischen Diagnosen. Benenne Unsicherheit ehrlich.
- Bei gesundheitlichen Auffälligkeiten: auf Fachperson/Arzt verweisen.
- Erfinde keine Werte; wenn Daten fehlen (z. B. Höhenmeter), sag das."""

DAILY = """Erstelle einen KURZEN täglichen Report auf Basis des Datensnapshots.
Format:
- Wo werde ich besser
- Wo schlechter
- 1 konkrete Anpassung
Halte es knapp (wenige Sätze)."""

WEEKLY = """Erstelle einen wöchentlichen Report über die drei Bereiche (Körper, Laufen, Kraft).
Format:
- Pro Bereich: was lief gut, worauf achten
- Genau EINE konkrete Anpassung für die kommende Woche
- Ein kurzer Motivationssatz zu dem, was gut lief."""


def build_messages(kind: str, snapshot: str, user_msg: str | None = None,
                   history: list[dict] | None = None) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}]
    msgs.append({"role": "system", "content": f"Aktueller Datensnapshot:\n{snapshot}"})

    if kind == "daily":
        msgs.append({"role": "user", "content": DAILY})
    elif kind == "weekly":
        msgs.append({"role": "user", "content": WEEKLY})
    else:  # chat
        for h in (history or []):
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": h["content"]})
        msgs.append({"role": "user", "content": user_msg or "Wie sieht mein Stand aus?"})
    return msgs
