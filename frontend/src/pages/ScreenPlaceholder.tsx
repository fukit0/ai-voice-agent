import type { Screen } from "../screens";

// İskelet sayfası: her ekran kendi feature'ında (lab-001…lab-005) gerçek içeriğine kavuşur.
export function ScreenPlaceholder({ screen }: { screen: Screen }) {
  return (
    <section className="screen">
      <h2>{screen.label}</h2>
      <p className="meta">
        {screen.featureId} · plan {screen.planRef} · henüz yapılmadı
      </p>
      <p>{screen.summary}</p>
    </section>
  );
}
