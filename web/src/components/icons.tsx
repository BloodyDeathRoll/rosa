/** Icon set from the Rosa App design handoff (lucide-style, stroke 1.5). */

interface IconProps {
  size?: number;
  /** stroke width override; the set's default is 1.5 */
  stroke?: number;
}

const base = {
  fill: "none",
  stroke: "currentColor",
  "stroke-width": 1.5,
  "stroke-linecap": "round",
  "stroke-linejoin": "round",
} as const;

export const HomeIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    <path d="M9 22V12h6v10" />
  </svg>
);

export const StarIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);

export const InfoIcon = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 16v-4M12 8h.01" />
  </svg>
);

/** Flag - the spot page's "Report an issue" button. */
export const FlagIcon = ({ size = 16 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
    <path d="M4 22v-7" />
  </svg>
);

export const MapIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M9 3l6 3 6-3v15l-6 3-6-3-6 3V6l6-3z" />
    <path d="M9 3v15" />
    <path d="M15 6v15" />
  </svg>
);

export const MapPinIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
    <circle cx="12" cy="10" r="3" />
  </svg>
);

export const GearIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

export const UserIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);

// Search and share default a size up and a stroke heavier than the set (2026-09-26): they
// are the header's two action buttons and read too faint at 18/1.5.
export const SearchIcon = ({ size = 20, stroke = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} stroke-width={stroke}>
    <circle cx="11" cy="11" r="8" />
    <path d="m21 21-4.3-4.3" />
  </svg>
);

/** Share - the Android three-node glyph, for every header's share button. */
export const ShareIcon = ({ size = 20, stroke = 2 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} stroke-width={stroke}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <path d="m8.59 13.51 6.83 3.98" />
    <path d="m15.41 6.51-6.82 3.98" />
  </svg>
);

export const CheckIcon = ({ size = 18, stroke = 1.5 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base} stroke-width={stroke}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

export const ChevronLeftIcon =({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="m15 18-6-6 6-6" />
  </svg>
);

export const ChevronRightIcon = ({ size = 14 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="m9 18 6-6-6-6" />
  </svg>
);

export const SunIcon = ({ size = 12 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2" />
    <path d="M12 20v2" />
    <path d="m4.93 4.93 1.41 1.41" />
    <path d="m17.66 17.66 1.41 1.41" />
    <path d="M2 12h2" />
    <path d="M20 12h2" />
    <path d="m6.34 17.66-1.41 1.41" />
    <path d="m19.07 4.93-1.41 1.41" />
  </svg>
);

export const MoonIcon = ({ size = 12 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
  </svg>
);

export const ThermometerIcon = ({ size = 15 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z" />
  </svg>
);

export const WavesIcon = ({ size = 15 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
    <path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1" />
  </svg>
);

export const ShirtIcon = ({ size = 15 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M20.38 3.46 16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z" />
  </svg>
);

/** Up arrow, rotated per direction of travel. Kept for anywhere still using
    the generic pointer; the hourly grid uses the distinct WindDirIcon/SwellDirIcon. */
export const ArrowIcon = ({ size = 12, rotate = 0 }: IconProps & { rotate?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    {...base}
    stroke-width={2}
    style={`transform:rotate(${rotate}deg)`}
  >
    <path d="M12 19V5" />
    <path d="m5 12 7-7 7 7" />
  </svg>
);

/** Wind direction - solid paper-plane pointer with a notched base.
    Distinct from swell: hard, unambiguous vane. */
export const WindDirIcon = ({ size = 14, rotate = 0 }: IconProps & { rotate?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    style={`transform:rotate(${rotate}deg);display:block`}
    aria-hidden="true"
  >
    <path
      d="M12 3 L20 20 L12 16 L4 20 Z"
      fill="currentColor"
      stroke="currentColor"
      stroke-width="1"
      stroke-linejoin="round"
    />
  </svg>
);

/** Swell direction - outlined arrow with a small trailing dot (wave source).
    Deliberately different silhouette from the wind vane. */
export const SwellDirIcon = ({ size = 14, rotate = 0 }: IconProps & { rotate?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    style={`transform:rotate(${rotate}deg);display:block`}
    aria-hidden="true"
  >
    <path d="M12 21V6" />
    <path d="m6 11 6-6 6 6" />
    <circle cx="12" cy="21" r="1" fill="currentColor" stroke="none" />
  </svg>
);

/** Video camera - marks a spot that has a live cam. */
export const CamIcon = ({ size = 15 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5" />
    <rect x="2" y="6" width="14" height="12" rx="2" />
  </svg>
);

/** Crosshair locate - circle, center dot, four ticks. */
export const LocateIcon = ({ size = 17 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <circle cx="12" cy="12" r="7" />
    <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
    <path d="M12 2v3" />
    <path d="M12 19v3" />
    <path d="M2 12h3" />
    <path d="M19 12h3" />
  </svg>
);

/** North needle + N - rotated by the map bearing so it always points north. */
export const CompassNorthIcon = ({ size = 17 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M12 3.5l3.6 8.5-3.6-1.8-3.6 1.8z" fill="currentColor" stroke="none" />
    <text
      x="12"
      y="21.5"
      text-anchor="middle"
      font-size="9"
      font-weight="700"
      fill="currentColor"
      stroke="none"
    >
      N
    </text>
  </svg>
);

export const XIcon = ({ size = 20 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
);

export const PlusIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const MinusIcon = ({ size = 18 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...base}>
    <path d="M5 12h14" />
  </svg>
);
