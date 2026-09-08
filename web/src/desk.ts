/** The one breakpoint the desktop layout hangs off - keep in step with the
    DESKTOP block in styles.css. Above it the app is a full-width page with a
    top bar; below it the phone layout with the floating nav pill. */
export const DESK_MQ = "(min-width: 900px)";

export const isDesk = (): boolean =>
  typeof matchMedia === "function" && matchMedia(DESK_MQ).matches;
