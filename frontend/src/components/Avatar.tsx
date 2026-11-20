const ICONS = ["🦊", "🐼", "🦉", "🐬", "🦁", "🐢", "🦋", "🐙", "🦄", "🐧", "🦒", "🐝"];
const TINTS = ["#E5F3EB", "#E8EFFB", "#FDF1DC", "#F8E6EE", "#EDE8FA", "#E3F4F4"];

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export default function Avatar({ seed, size = 40, label }: { seed: string; size?: number; label?: string }) {
  const h = hash(seed || "?");
  return (
    <span
      className="avatar"
      role="img"
      aria-label={label ? `Icône de ${label}` : "Icône du profil"}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.52), background: TINTS[(h >> 4) % TINTS.length] }}
    >
      {ICONS[h % ICONS.length]}
    </span>
  );
}
